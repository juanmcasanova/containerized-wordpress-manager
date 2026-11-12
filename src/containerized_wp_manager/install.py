import os
import shutil
import subprocess
import sys

import click
import docker
from rich.console import Console
from rich.progress import Progress

from containerized_wp_manager.check import check_environment

MARIADB_TAG = '12.3'
NGINX_TAG = '1.31'
PHP_TAG = '8.5-fpm'

def install_environment() -> None:
    """Configures everything missing to ensure the environment is right."""
    docker_client = docker.from_env()
    console = Console()

    checks = check_environment()

    # Always try to create the directory (if it already exists, nothing is lost)
    # TODO: See how we can make sure we have enough permissions
    try:
        os.makedirs('/opt/containerized-wp-manager', exist_ok=True)
        os.makedirs('/opt/containerized-wp-manager/sites', exist_ok=True)
        os.makedirs('/opt/containerized-wp-manager/conf', exist_ok=True)
        os.makedirs('/opt/containerized-wp-manager/certbot', exist_ok=True)
        os.makedirs('/opt/containerized-wp-manager/certbot/etc', exist_ok=True)
        os.makedirs('/opt/containerized-wp-manager/certbot/var', exist_ok=True)
        os.makedirs('/opt/containerized-wp-manager/certbot/log', exist_ok=True)
    except PermissionError:
        console.print('The executing user has no permissions to create the folder /opt/containerized-wp-manager, create it by hand and assign it to the right user.', style='red')
        click.get_current_context().exit(1)

    with Progress() as progress:
        if not checks['networks']['success']:
            networks_task = progress.add_task("Creating necessary networks...", total=100)
            # TODO: We could have one but not the other, we should check
            docker_client.networks.list()
            docker_client.networks.create('cwpm-services')
            progress.update(networks_task, advance=50)
            docker_client.networks.create('cwpm-proxy')
            progress.update(networks_task, advance=100)

        if not checks['containers']['success']:
            containers_task = progress.add_task("Creating necessary containers...", total=100)
            start_nginx_container(docker_client)
            progress.update(containers_task, advance=50)
            start_mariadb_container(docker_client)
            progress.update(containers_task, advance=100)

        # The image build *always* has to be the last task, as it is not compatible with the progress indicator
        progress.stop()
        if not checks['images']['success']:
            build_php_image()

def start_nginx_container(docker_client: docker.DockerClient) -> None:
    """Starts the Nginx container and copies the default configuration needed for it to the right place."""
    shutil.copy2(f'{os.path.dirname(os.path.abspath(__file__))}/resources/nginx-default.conf', '/opt/containerized-wp-manager/conf/000-default.conf')
    docker_client.images.pull(f'nginx:{NGINX_TAG}')
    docker_client.containers.run(
        image=f'nginx:{NGINX_TAG}',
        detach=True,
        name='cwpm-nginx',
        volumes=[
            '/opt/containerized-wp-manager/conf:/etc/nginx/conf.d:ro',
            '/opt/containerized-wp-manager/sites:/var/www/html:ro',
            '/opt/containerized-wp-manager/certbot/etc:/etc/ssl/certbot:ro',
        ],
        ports={'80/tcp': 80, '443/tcp': 443},
        restart_policy={"Name": 'always'},
        network='cwpm-proxy'
    )

def start_mariadb_container(docker_client: docker.DockerClient) -> None:
    """Starts the MariaDB container."""
    docker_client.images.pull(f'mariadb:{MARIADB_TAG}')
    docker_client.containers.run(
        image=f'mariadb:{MARIADB_TAG}',
        detach=True,
        name='cwpm-mariadb',
        volumes=['/opt/containerized-wp-manager/mariadb:/var/lib/mysql:Z'],
        ports={'3306/tcp': 3306},
        restart_policy={"Name": 'always'},
        network='cwpm-services',
        # TODO: Obviously, change this!
        # TODO: We should have a specific user for cwpm, never use root (and disable `root`@`%`)
        environment={'MARIADB_ROOT_PASSWORD': 'root'}
    )

def build_php_image() -> None:
    """Builds the shared PHP image that will be used in every site."""
    # TODO: docker-py is not compatible with BuildKit: https://github.com/docker/docker-py/issues/2230
    #       https://github.com/aio-libs/aiodocker seems to be
    subprocess.run(['docker', 'buildx', 'build', '-t', 'cwpm-php-fpm', f'{os.path.dirname(os.path.abspath(__file__))}/resources', '--no-cache', '--pull', '--build-arg', f'BASE_PHP={PHP_TAG}'], stdout=sys.stdout, stderr=sys.stderr, check=True)
