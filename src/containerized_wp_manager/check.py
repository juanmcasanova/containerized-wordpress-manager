import click
import docker
from rich.console import Console
from rich.table import Table
from rich.text import Text

CHECKS_MAP = {'version': 'Docker version', 'networks': 'Docker networks', 'containers': 'Docker containers'}

def check_environment() -> dict:
    checks = {}
    # TODO: All errors should be displayed at the same time, not one at a time
    docker_client = docker.from_env()

    # Get Docker version (minimal check to ensure Docker is installed and reachable)
    checks['version'] = {'success': True, 'context': f'Detected version: {docker_client.version()['Version']}'}
    # TODO: Check for the KO too (right now it will crash)
    # TODO: Check that BuildX is installed

    # Check if all networks exist
    missing_networks = ['cwpm-services', 'cwpm-proxy']
    for network in docker_client.networks.list(names=missing_networks):
        if network.name in missing_networks:
            missing_networks.pop(missing_networks.index(network.name))
    checks['networks'] = {'success' : not missing_networks, 'context': None}
    if missing_networks:
        checks['networks']['context'] = f'Missing networks: {missing_networks}'

    # Get a list of available containers to know if we already have everything configured
    missing_containers=['cwpm-nginx', 'cwpm-mariadb']
    for container in docker_client.containers.list(filters={'name': missing_containers}, all=True):
        if container.name in missing_containers:
            missing_containers.pop(missing_containers.index(container.name))
    checks['containers'] = {'success' : not missing_containers, 'context': None}
    if missing_containers:
        checks['containers']['context'] = f'Missing containers: {missing_containers}'

    return checks

def check_and_print() -> None:
    checks = check_environment()

    table = Table(title='Environment check')
    table.add_column('Check')
    table.add_column('Status')
    table.add_column('Details')

    ok = Text('OK', style='green')
    ko = Text('KO', style='red')

    any_fail = False
    for check, result in checks.items():
        any_fail = any_fail or not result['success']
        table.add_row(
            CHECKS_MAP.get(check, check),
            ok if result['success'] else ko,
            result.get('context', '')
        )

    console = Console()
    console.print(table)

    if not any_fail:
        console.print('Everything seems to be okay, you are good to go!', style='green')
    else:
        console.print('At least one check failed, review the errors and run `containerized-wp-manager install` to fix them (usually).', style='red')
        click.get_current_context().exit(1)
