import os
import shutil
import zipfile
from urllib.request import urlretrieve

import docker
import pymysql
import yaml
from rich.console import Console
from rich.progress import Progress, TaskID
from slugify import slugify


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

def add_instance(domain: str, aliases: list[str], skip_ssl: bool) -> None:
    """Adds everything needed for a new WordPress instance."""
    # TODO: Check (and fail) if the instance already exists
    # TODO: Ensure we never let the temp folder stay if something fails
    os.makedirs('/tmp/cwpm')

    id = slugify(domain, separator='_')

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
        with open(f'/opt/containerized-wp-manager/sites/{id}/.cwpm-config.yaml', 'w') as alias_config:
            alias_config.writelines(yaml.dump({'domain': domain, 'http-only': skip_ssl, 'aliases': aliases}))

        # Create a site folder for each alias to use with Certbot and to save the needed configuration file
        for alias in aliases:
            os.mkdir(f'/opt/containerized-wp-manager/sites/{slugify(alias, separator='_')}')
            with open(f'/opt/containerized-wp-manager/sites/{slugify(alias, separator='_')}/.cwpm-alias.yaml', 'w') as alias_config:
                alias_config.writelines(yaml.dump({'domain': alias, 'http-only': skip_ssl, 'main-domain': domain}))

        mariadb_task = progress.add_task("Configuring MariaDB...", total=100)
        configure_mariadb(id, progress, mariadb_task)

        wordpress_task = progress.add_task("Configuring WordPress...", total=100)
        configure_wordpress(id)
        progress.update(wordpress_task, advance=100)

        docker_client = docker.from_env()

        container_task = progress.add_task("Creating Docker container...", total=100)
        container = docker_client.containers.run(
            image='cwpm-php-fpm:latest',
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
            docker_client.containers.run(
                image='certbot/certbot',
                name='cwpm-certbot',
                volumes=[
                    f'/opt/containerized-wp-manager/certbot/etc/{id}:/etc/letsencrypt:rw',
                    f'/opt/containerized-wp-manager/certbot/var/{id}:/var/lib/letsencrypt:rw',
                    f'/opt/containerized-wp-manager/certbot/log/{id}:/var/log/letsencrypt:rw',
                    f'/opt/containerized-wp-manager/sites/{id}:/var/www/html:rw'
                ],
                command=f'certonly --non-interactive --agree-tos --webroot -w /var/www/html -d {domain}',
                auto_remove=True
            )
            for alias in aliases:
                docker_client.containers.run(
                    image='certbot/certbot',
                    name='cwpm-certbot',
                    volumes=[
                        f'/opt/containerized-wp-manager/certbot/etc/{slugify(alias, separator='_')}:/etc/letsencrypt:rw',
                        f'/opt/containerized-wp-manager/certbot/var/{slugify(alias, separator='_')}:/var/lib/letsencrypt:rw',
                        f'/opt/containerized-wp-manager/certbot/log/{slugify(alias, separator='_')}:/var/log/letsencrypt:rw',
                        f'/opt/containerized-wp-manager/sites/{slugify(alias, separator='_')}:/var/www/html:rw'
                    ],
                    command=f'certonly --non-interactive --agree-tos --webroot -w /var/www/html -d {alias}',
                    auto_remove=True
                )
            progress.update(certbot_container, advance=50)

            # Configure the SSL sites with the newly created certificates
            with open(f'{os.path.dirname(os.path.abspath(__file__))}/resources/nginx-sites/https.conf', 'r') as template, open(f'/opt/containerized-wp-manager/conf/{id}-https.conf', 'w', newline='\n') as config:
                config.writelines(line.replace('<CWPM_DOMAIN>', domain).replace('<CWPM_ID>', id) for line in template)

            for alias in aliases:
                with open(f'{os.path.dirname(os.path.abspath(__file__))}/resources/nginx-sites/alias-https.conf', 'r') as template, open(f'/opt/containerized-wp-manager/conf/{slugify(alias, separator='_')}-https.conf', 'w', newline='\n') as config:
                    config.writelines(line.replace('<CWPM_DOMAIN>', alias).replace('<CWPM_MAIN_DOMAIN>', domain).replace('<CWPM_ID>', slugify(alias, separator='_')) for line in template)

            # Send a signal to Nginx to gracefully reload configuration
            docker_client.containers.list(filters={'name': 'cwpm-nginx'})[0].exec_run('nginx -s reload')

    console = Console()
    console.print(f'The site has correctly initialized, you can now access it via your browser in: http{'s' if not skip_ssl else ''}://{domain}', style='green')
