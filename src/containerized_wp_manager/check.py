import os

import click
import docker


def check_environment() -> None:
    # TODO: All errors should be displayed at the same time, not one at a time
    docker_client = docker.from_env()

    # Get Docker version (minimal check to ensure Docker is installed and reachable)
    click.echo(f'Docker version: {docker_client.version()['Version']}')
    # TODO: Check that BuildX is installed

    # Check if both networks exist
    missing_networks = ['cwpm-services', 'cwpm-proxy']
    for network in docker_client.networks.list(names=missing_networks):
        if network.name in missing_networks:
            missing_networks.pop(missing_networks.index(network.name))
    if missing_networks:
        click.echo(click.style(f'The following networks weren\'t found: {missing_networks}. Run `wp-docker-manager install` to create them.', fg='yellow'))
        click.get_current_context().exit(1)

    # Check if the HAProxy configuration file exists
    if not os.path.isfile('/opt/wp-docker-manager/haproxy.cfg'):
        click.echo(click.style('No HAProxy configuration file was found, run `wp-docker-manager install` to create it.', fg='yellow'))
        click.get_current_context().exit(1)

    # Get a list of available containers to know if we already have everything configured
    missing_containers=['cwpm-haproxy', 'cwpm-mariadb']
    for container in docker_client.containers.list(filters={'name': missing_containers}, all=True):
        if container.name in missing_containers:
            missing_containers.pop(missing_containers.index(container.name))
    if missing_containers:
        click.echo(click.style(f'The following containers weren\'t found: {missing_containers}. Run `wp-docker-manager install` to create them.', fg='yellow'))
        click.get_current_context().exit(1)

    click.echo(click.style('Everything seems right!', fg='green'))
