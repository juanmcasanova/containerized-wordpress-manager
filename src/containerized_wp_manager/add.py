import os
import shutil
import subprocess
import sys
import zipfile
from urllib.request import urlretrieve

import click
import docker
import pymysql


def configure_mariadb(site_id: str) -> None:
    """Configures the MariaDB database with everything necessary for WordPress to work."""
    with pymysql.connect(user='root', password='root', host='127.0.0.1', port=3306) as connection, connection.cursor() as cursor:
        # TODO: We should configure the network so we can limit this to the Docker subnet
        cursor.execute(f'CREATE USER `cwpm_{site_id}`@`%` IDENTIFIED BY \'test\'')
        cursor.execute(f'CREATE DATABASE cwpm_{site_id}')
        cursor.execute(f'GRANT ALL PRIVILEGES ON cwpm_{site_id}.* TO `cwpm_{site_id}`@`%`')

def configure_wordpress(site_id: str) -> None:
    """
    Configures the wp-config.php file for WordPress.
    """

    with open(f'/opt/containerized-wp-manager/sites/{site_id}/wp-config-sample.php', 'r') as input, open(f'/opt/containerized-wp-manager/sites/{site_id}/wp-config.php', 'w') as output:
        for line in input:
            if 'database_name_here' in line:
                line = line.replace('database_name_here', f'cwpm_{site_id}')
            elif 'username_here' in line:
                line = line.replace('username_here', f'cwpm_{site_id}')
            elif 'password_here' in line:
                line = line.replace('password_here', 'test')
            elif 'DB_HOST' in line:
                line = line.replace('localhost', 'cwpm-mariadb')

            output.write(line)

def add_instance(id: str, domain: str) -> None:
    """Adds everything needed for a new WordPress instance."""
    # TODO: Check (and fail) if the instance already exists
    os.makedirs('/tmp/cwpm')

    click.echo('Downloading WordPress...')
    url = "https://wordpress.org/latest.zip"
    filename = "/tmp/cwpm/wp-latest.zip"
    urlretrieve(url, filename)

    click.echo('Extracting WordPress...')
    with zipfile.ZipFile(filename, 'r') as zf:
        zf.extractall('/opt/containerized-wp-manager/sites')

    os.rename('/opt/containerized-wp-manager/sites/wordpress', f'/opt/containerized-wp-manager/sites/{id}')
    shutil.rmtree('/tmp/cwpm')

    click.echo('Configuring MariaDB...')
    configure_mariadb(id)
    click.echo('Configuring WordPress...')
    configure_wordpress(id)

    docker_client = docker.from_env()
    click.echo('Building Docker image...')
    # TODO: docker-py is not compatible with BuildKit: https://github.com/docker/docker-py/issues/2230
    #       https://github.com/aio-libs/aiodocker seems to be
    subprocess.run(['docker', 'buildx', 'build', '-t', f'cwpm-{id}', f'{os.path.dirname(os.path.abspath(__file__))}/resources'], stdout=sys.stdout, stderr=sys.stderr, check=True)

    click.echo('Creating Docker container...')
    container = docker_client.containers.run(
        image=f'cwpm-{id}:latest',
        detach=True,
        name=f'cwpm-{id}',
        volumes=[f'/opt/containerized-wp-manager/sites/{id}:/var/www/html:rw'],
        restart_policy={"Name": 'always'},
        network='cwpm-proxy',
        user=os.getuid()
    )
    docker_client.networks.list(names='cwpm-services')[0].connect(container)

    with open(f'{os.path.dirname(os.path.abspath(__file__))}/resources/nginx.conf', 'r') as template, open(f'/opt/containerized-wp-manager/conf/{id}.conf', 'w', newline='\n') as config:
        for line in template:
            config.write(line.replace('<CWPM_DOMAIN>', domain).replace('<CWPM_ID>', id))

    # Send a signal to Nginx to gracefully reload configuration
    docker_client.containers.list(filters={'name': 'cwpm-nginx'})[0].exec_run('nginx -s reload')
