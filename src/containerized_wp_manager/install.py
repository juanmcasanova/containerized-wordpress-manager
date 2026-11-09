import os
import shutil

import click
import docker
from rich.console import Console
from rich.progress import Progress

from containerized_wp_manager.check import check_environment


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
    except PermissionError:
        console.print('The executing user has no permissions to create the folder /opt/containerized-wp-manager, create it by hand and assign it to the right user.', style='red')
        click.get_current_context().exit(1)

    with Progress() as progress:
        if not checks['haproxy_config']['success']:
            haproxy_config_task = progress.add_task("Copying HAProxy config file...", total=100)
            shutil.copyfile(f'{os.path.dirname(os.path.abspath(__file__))}/resources/haproxy.cfg', '/opt/containerized-wp-manager/haproxy.cfg')
            progress.update(haproxy_config_task, advance=100)

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
            docker_client.containers.run(
                image='haproxy:3.4-alpine',
                detach=True,
                name='cwpm-haproxy',
                volumes=['/opt/containerized-wp-manager/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro'],
                ports={'80/tcp': 80},
                restart_policy={"Name": 'always'},
                network='cwpm-proxy'
            )
            progress.update(containers_task, advance=50)
            docker_client.containers.run(
                image='mariadb:12.3',
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
            progress.update(containers_task, advance=100)
