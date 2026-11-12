import os
import re
import secrets
import shutil
import string
import zipfile
from urllib.request import urlretrieve

import click
import docker
import pymysql
import yaml
from rich.console import Console
from rich.progress import Progress, TaskID
from slugify import slugify

from containerized_wp_manager.install import MARIADB_TAG


def configure_mariadb(site_id: str, docker_client: docker.DockerClient, database_dump: str|None, progress: Progress, task: TaskID) -> str:
    """Configures the MariaDB database with everything necessary for WordPress to work.

    Returns
    -------
    str
        The generated password for the site.
    """
    with pymysql.connect(user='root', password='root', host='127.0.0.1', port=3306) as connection, connection.cursor() as cursor:
        # TODO: We should configure the network so we can limit this to the Docker subnet
        # Copied from the Python documentation: https://docs.python.org/3/library/secrets.html#recipes-and-best-practices
        allowed_chars = '|+-.,;:¿?=)(=%&$~·#@'
        alphabet = string.ascii_letters + string.digits + allowed_chars
        password = None
        while True:
            password = ''.join(secrets.choice(alphabet) for _ in range(14))
            if (any(c.islower() for c in password)
                    and any(c.isupper() for c in password)
                    and any(c.isdigit() for c in password)
                    and any(c in '|+-.,;:¿?=)(=%&$~·#@' for c in password)):
                break
        cursor.execute(f'CREATE USER `cwpm_{site_id}`@`%` IDENTIFIED BY \'{password}\'')
        progress.update(task, advance=1)
        cursor.execute(f'CREATE DATABASE cwpm_{site_id}')
        progress.update(task, advance=1)
        cursor.execute(f'GRANT ALL PRIVILEGES ON cwpm_{site_id}.* TO `cwpm_{site_id}`@`%`')
        progress.update(task, advance=1)
        if database_dump:
            # Using Python is troublesome, use the MariaDB client and forget about it
            docker_client.containers.run(
                image=f'mariadb:{MARIADB_TAG}',
                auto_remove=True,
                name='cwpm-mariadb-import',
                volumes=[f'{database_dump}:/tmp/dump.sql:ro'],
                network='cwpm-services',
                environment={'MARIADB_ALLOW_EMPTY_ROOT_PASSWORD': '1'},
                entrypoint='',
                command=f'mariadb -u root -proot -h cwpm-mariadb cwpm_{site_id} -e "SOURCE /tmp/dump.sql"',
                stdout=True,
                stderr=True
            )
            progress.update(task, advance=1)

    return password

def configure_wordpress(site_id: str, mariadb_password: str, prefix: str|None) -> None:
    """Configures the wp-config.php file for WordPress."""
    # If the wp-config.php file already exists, use it as the source (that ensures custom configurations remain on import)
    original_file = None
    if os.path.isfile(f'/opt/containerized-wp-manager/sites/{site_id}/wp-config.php'):
        with open(f'/opt/containerized-wp-manager/sites/{site_id}/wp-config.php', 'r', newline='\n') as input:
            original_file = input.read()
    else:
        with open(f'/opt/containerized-wp-manager/sites/{site_id}/wp-config-sample.php', 'r', newline='\n') as input:
            original_file = input.read()

    with open(f'/opt/containerized-wp-manager/sites/{site_id}/wp-config.php', 'w') as output:
        original_file = re.sub('define\\(\\s?\'DB_NAME\',\\s?\'.*\'\\s?\\);', f'define( \'DB_NAME\', \'cwpm_{site_id}\' );', original_file)
        original_file = re.sub('define\\(\\s?\'DB_USER\',\\s?\'.*\'\\s?\\);', f'define( \'DB_USER\', \'cwpm_{site_id}\' );', original_file)
        original_file = re.sub('define\\(\\s?\'DB_PASSWORD\',\\s?\'.*\'\\s?\\);', f'define( \'DB_PASSWORD\', \'{mariadb_password}\' );', original_file)
        original_file = re.sub('define\\(\\s?\'DB_HOST\',\\s?\'.*\'\\s?\\);', 'define( \'DB_HOST\', \'cwpm-mariadb\' );', original_file)
        # Don't touch the prefix if not set (this allows importing custom-prefix sites without setting it explicitly)
        if prefix:
            original_file = re.sub('\\$table_prefix\\s?=\\s?\'.*\';', f'$table_prefix = \'{prefix}\';', original_file)

        output.write(original_file)

def start_container(id:str, docker_client: docker.DockerClient) -> None:
    container = docker_client.containers.run(
        image='cwpm-php-fpm:latest',
        detach=True,
        name=f'cwpm-{id}',
        volumes=[f'/opt/containerized-wp-manager/sites/{id}:/var/www/html:rw'],
        restart_policy={"Name": 'always'},
        network='cwpm-proxy',
        user=os.getuid()
    )
    docker_client.networks.list(names='cwpm-services')[0].connect(container)

def add_instance(domain: str, aliases: list[str], skip_ssl: bool, prefix: str|None = None, zip_path: str|None = None, database_dump: str|None = None) -> None:
    """Adds everything needed for a new WordPress instance."""
    # TODO: Check (and fail) if the instance already exists
    os.makedirs('/tmp/cwpm/site')

    id = slugify(domain, separator='_')
    console = Console()

    with Progress() as progress:
        try:
            filename = zip_path
            if not filename:
                filename = '/tmp/cwpm/wp-latest.zip'
                download_task = progress.add_task("Downloading WordPress...", total=100)
                urlretrieve('https://wordpress.org/latest.zip', filename)
                progress.update(download_task, advance=100)

            extraction_task = progress.add_task("Extracting WordPress...", total=100)
            with zipfile.ZipFile(filename, 'r') as zf:
                zf.extractall('/tmp/cwpm/site')
            progress.update(extraction_task, advance=100)

            # If there is a wp-config.php in the root of the folder, it should mean the whole WordPress is there
            if os.path.isfile('/tmp/cwpm/site/wp-config.php'):
                shutil.move('/tmp/cwpm/site', f'/opt/containerized-wp-manager/sites/{id}')
            else:
                extracted_files = os.listdir('/tmp/cwpm/site')
                # Only move if there is only one element extracted, it is a directory and contains a wp-config.php (or wp-config-sample.php) file
                if 1 == len(extracted_files) and os.path.isdir(f'/tmp/cwpm/site/{extracted_files[0]}') and (os.path.isfile(f'/tmp/cwpm/site/{extracted_files[0]}/wp-config.php') or os.path.isfile(f'/tmp/cwpm/site/{extracted_files[0]}/wp-config-sample.php')):
                    shutil.move(f'/tmp/cwpm/site/{extracted_files[0]}', f'/opt/containerized-wp-manager/sites/{id}')
                else:
                    progress.stop()
                    console.print('Cannot detect the ZIP structure! It must have either directly the files o a directory containing all the files.', style='red')
                    click.get_current_context().exit(1)
        finally:
            shutil.rmtree('/tmp/cwpm')

        with open(f'/opt/containerized-wp-manager/sites/{id}/.cwpm-config.yaml', 'w') as alias_config:
            alias_config.writelines(yaml.dump({'domain': domain, 'http-only': skip_ssl, 'aliases': aliases}))

        # Create a site folder for each alias to use with Certbot and to save the needed configuration file
        for alias in aliases:
            os.mkdir(f'/opt/containerized-wp-manager/sites/{slugify(alias, separator='_')}')
            with open(f'/opt/containerized-wp-manager/sites/{slugify(alias, separator='_')}/.cwpm-alias.yaml', 'w') as alias_config:
                alias_config.writelines(yaml.dump({'domain': alias, 'http-only': skip_ssl, 'main-domain': domain}))

        docker_client = docker.from_env()

        mariadb_task = progress.add_task("Configuring MariaDB...", total=3 if database_dump is None else 4)
        mariadb_password = configure_mariadb(id, docker_client, database_dump, progress, mariadb_task)

        wordpress_task = progress.add_task("Configuring WordPress...", total=100)
        configure_wordpress(id, mariadb_password, prefix)
        progress.update(wordpress_task, advance=100)

        container_task = progress.add_task("Creating Docker container...", total=100)
        start_container(id, docker_client)
        progress.update(container_task, advance=100)

        # Configure only the HTTP part of the site (and aliases) so we can generate a valid SSL certificate
        with open(f'{os.path.dirname(os.path.abspath(__file__))}/resources/nginx-sites/http{'-only' if skip_ssl else '' }.conf', 'r') as template, open(f'/opt/containerized-wp-manager/conf/{id}-http.conf', 'w', newline='\n') as config:
            config.writelines(line.replace('<CWPM_DOMAIN>', domain).replace('<CWPM_ID>', id) for line in template)

        for alias in aliases:
            with open(f'{os.path.dirname(os.path.abspath(__file__))}/resources/nginx-sites/alias-http{'-only' if skip_ssl else ''}.conf', 'r') as template, open(f'/opt/containerized-wp-manager/conf/{slugify(alias, separator='_')}-http.conf', 'w', newline='\n') as config:
                config.writelines(line.replace('<CWPM_DOMAIN>', alias).replace('<CWPM_ID>', slugify(alias, separator='_')).replace('<CWPM_MAIN_DOMAIN>', domain) for line in template)

        # Send a signal to Nginx to gracefully reload configuration
        docker_client.containers.list(filters={'name': 'cwpm-nginx'})[0].exec_run('nginx -s reload')

        if not skip_ssl:
            certbot_container = progress.add_task("Generating SSL certificate...", total=100)
            progress.update(certbot_container, advance=50)
            container = docker_client.containers.run(
                image='certbot/certbot',
                name='cwpm-certbot',
                volumes=[
                    f'/opt/containerized-wp-manager/certbot/etc/{id}:/etc/letsencrypt:rw',
                    f'/opt/containerized-wp-manager/certbot/var/{id}:/var/lib/letsencrypt:rw',
                    f'/opt/containerized-wp-manager/certbot/log/{id}:/var/log/letsencrypt:rw',
                    f'/opt/containerized-wp-manager/sites/{id}:/var/www/html:rw'
                ],
                command=f'certonly --non-interactive --agree-tos --webroot -w /var/www/html -d {domain}',
                detach=True,
            )
            container.wait()
            container.remove()
            for alias in aliases:
                container = docker_client.containers.run(
                    image='certbot/certbot',
                    name='cwpm-certbot',
                    volumes=[
                        f'/opt/containerized-wp-manager/certbot/etc/{slugify(alias, separator='_')}:/etc/letsencrypt:rw',
                        f'/opt/containerized-wp-manager/certbot/var/{slugify(alias, separator='_')}:/var/lib/letsencrypt:rw',
                        f'/opt/containerized-wp-manager/certbot/log/{slugify(alias, separator='_')}:/var/log/letsencrypt:rw',
                        f'/opt/containerized-wp-manager/sites/{slugify(alias, separator='_')}:/var/www/html:rw'
                    ],
                    command=f'certonly --non-interactive --agree-tos --webroot -w /var/www/html -d {alias}',
                    detach=True
                )
                container.wait()
                container.remove()
            progress.update(certbot_container, advance=50)

            # Configure the SSL sites with the newly created certificates
            with open(f'{os.path.dirname(os.path.abspath(__file__))}/resources/nginx-sites/https.conf', 'r') as template, open(f'/opt/containerized-wp-manager/conf/{id}-https.conf', 'w', newline='\n') as config:
                config.writelines(line.replace('<CWPM_DOMAIN>', domain).replace('<CWPM_ID>', id) for line in template)

            for alias in aliases:
                with open(f'{os.path.dirname(os.path.abspath(__file__))}/resources/nginx-sites/alias-https.conf', 'r') as template, open(f'/opt/containerized-wp-manager/conf/{slugify(alias, separator='_')}-https.conf', 'w', newline='\n') as config:
                    config.writelines(line.replace('<CWPM_DOMAIN>', alias).replace('<CWPM_MAIN_DOMAIN>', domain).replace('<CWPM_ID>', slugify(alias, separator='_')) for line in template)

            # Send a signal to Nginx to gracefully reload configuration
            docker_client.containers.list(filters={'name': 'cwpm-nginx'})[0].exec_run('nginx -s reload')

    console.print(f'The site has correctly initialized, you can now access it via your browser in: http{'s' if not skip_ssl else ''}://{domain}', style='green')
