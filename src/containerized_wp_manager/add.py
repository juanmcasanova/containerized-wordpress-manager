import os
import shutil
import subprocess
import sys
import zipfile
from urllib.request import urlretrieve

import docker
import pymysql
from rich.console import Console
from rich.progress import Progress, TaskID


def configure_mariadb(site_id: str, progress: Progress, task: TaskID) -> None:
    """Configures the MariaDB database with everything necessary for WordPress to work."""
    with pymysql.connect(user='root', password='root', host='127.0.0.1', port=3306) as connection, connection.cursor() as cursor:
        # TODO: We should configure the network so we can limit this to the Docker subnet
        cursor.execute(f'CREATE USER `cwpm_{site_id}`@`%` IDENTIFIED BY \'test\'')
        progress.update(task, advance=33)
        cursor.execute(f'CREATE DATABASE cwpm_{site_id}')
        progress.update(task, advance=33)
        cursor.execute(f'GRANT ALL PRIVILEGES ON cwpm_{site_id}.* TO `cwpm_{site_id}`@`%`')
        progress.update(task, advance=34)

def configure_wordpress(site_id: str) -> None:
    """Configures the wp-config.php file for WordPress."""
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

    with Progress() as progress:
        download_task = progress.add_task("Downloading WordPress...", total=100)
        filename = '/tmp/cwpm/wp-latest.zip'
        urlretrieve('https://wordpress.org/latest.zip', filename)
        progress.update(download_task, advance=100)

        extraction_task = progress.add_task("Extracting WordPress...", total=100)
        with zipfile.ZipFile(filename, 'r') as zf:
            zf.extractall('/opt/containerized-wp-manager/sites')
        progress.update(extraction_task, advance=100)

        os.rename('/opt/containerized-wp-manager/sites/wordpress', f'/opt/containerized-wp-manager/sites/{id}')
        shutil.rmtree('/tmp/cwpm')

        mariadb_task = progress.add_task("Configuring MariaDB...", total=100)
        configure_mariadb(id, progress, mariadb_task)

        wordpress_task = progress.add_task("Configuring WordPress...", total=100)
        configure_wordpress(id)
        progress.update(wordpress_task, advance=100)

        progress.stop()
        # TODO: docker-py is not compatible with BuildKit: https://github.com/docker/docker-py/issues/2230
        #       https://github.com/aio-libs/aiodocker seems to be
        subprocess.run(['docker', 'buildx', 'build', '-t', f'cwpm-{id}', f'{os.path.dirname(os.path.abspath(__file__))}/resources'], stdout=sys.stdout, stderr=sys.stderr, check=True)

        progress.remove_task(download_task)
        progress.remove_task(extraction_task)
        progress.remove_task(mariadb_task)
        progress.remove_task(wordpress_task)
        progress.start()
        docker_client = docker.from_env()

        container_task = progress.add_task("Creating Docker container...", total=100)
        container = docker_client.containers.run(
            image=f'cwpm-{id}:latest',
            detach=True,
            name=f'cwpm-{id}',
            volumes=[f'/opt/containerized-wp-manager/sites/{id}:/var/www/html:rw'],
            restart_policy={"Name": 'always'},
            network='cwpm-proxy',
            user=os.getuid()
        )
        progress.update(container_task, advance=50)
        docker_client.networks.list(names='cwpm-services')[0].connect(container)
        progress.update(container_task, advance=50)

        certbot_container = progress.add_task("Generating SSL certificate...", total=100)
        with open(f'{os.path.dirname(os.path.abspath(__file__))}/resources/nginx.conf', 'r') as template, open(f'/opt/containerized-wp-manager/conf/{id}.conf', 'w', newline='\n') as config:
            for line in template:
                config.write(line.replace('<CWPM_DOMAIN>', domain).replace('<CWPM_ID>', id))
        progress.update(certbot_container, advance=33)
        # Send a signal to Nginx to gracefully reload configuration
        docker_client.containers.list(filters={'name': 'cwpm-nginx'})[0].exec_run('nginx -s reload')
        progress.update(certbot_container, advance=33)
        docker_client.containers.run(
            image='certbot/certbot',
            name='cwpm-certbot',
            volumes=[
                f'/opt/containerized-wp-manager/certbot/etc/{id}:/etc/letsencrypt:rw',
                f'/opt/containerized-wp-manager/certbot/var/{id}:/var/lib/letsencrypt:rw',
                f'/opt/containerized-wp-manager/certbot/log/{id}:/var/log/letsencrypt:rw',
                f'/opt/containerized-wp-manager/sites/{id}:/var/www/html:rw'
            ],
            command=f'certonly --non-interactive --agree-tos --webroot -w /var/www/html -d {domain}'
        )
        progress.update(certbot_container, advance=34)

        # Recreate the template but with SSL enabled now
        # TODO: We could probably have two different config files, that will make this easier
        with open(f'{os.path.dirname(os.path.abspath(__file__))}/resources/nginx.conf', 'r') as template, open(f'/opt/containerized-wp-manager/conf/{id}.conf', 'w', newline='\n') as config:
            for line in template:
                config.write(line.replace('<CWPM_DOMAIN>', domain).replace('<CWPM_ID>', id).replace('#ssl_certificate', 'ssl_certificate').replace('#ssl_certificate_key', 'ssl_certificate_key'))

        # Send a signal to Nginx to gracefully reload configuration
        docker_client.containers.list(filters={'name': 'cwpm-nginx'})[0].exec_run('nginx -s reload')

    console = Console()
    console.print(f'The site has correctly initialized, you can now access it via your browser in: https://{domain}', style='green')
