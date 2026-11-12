import os

import click
from rich.console import Console

from containerized_wp_manager.add import add_instance
from containerized_wp_manager.check import check_and_print
from containerized_wp_manager.cleanup import perform_cleanup
from containerized_wp_manager.install import install_environment
from containerized_wp_manager.list import list_instances
from containerized_wp_manager.renew import renew_certs
from containerized_wp_manager.update import update_containers


@click.group()
def main() -> None:
    """
    CLI application to manage WordPress instances in a shared Docker environment
    """

@main.command('check')
def check() -> None:
    """
    Checks the current environment to ensure everything is right.
    """
    check_and_print()

@main.command('install')
def install() -> None:
    """
    Configures everything missing to ensure the environment is right.
    """
    install_environment()

@main.command('list')
def list_command() -> None:
    """
    Lists all currently available instances.
    """
    list_instances()

@main.command('add')
@click.argument('domain', help='Domain where the new instance will be served at')
@click.option('--skip-ssl', is_flag=True, help='Skip SSL configuration and certificate generation when configuring Nginx')
@click.option('--alias', '-a', multiple=True, help='Additional domains that will redirect to the main domain')
@click.option('--prefix', '-p', help='Custom database prefix that will be used in the WordPress configuration')
def add(domain: str, skip_ssl: bool, alias: list[str], prefix: str|None) -> None:
    """Adds a new configured WordPress instance."""
    # TODO: We should validate that domain is actually a domain
    console = Console()

    if skip_ssl:
        console.print('Configuring HTTP-only site, this should only be used for testing purposes!', style='yellow')

    add_instance(domain, alias, skip_ssl, prefix)

@main.command('import')
@click.argument('domain', help='Domain where the new instance will be served at')
@click.argument('archive', help='Path to the ZIP file that contains the WordPress instance')
@click.argument('database-dump', help='Path to the SQL file that has to be imported to the database')
@click.option('--skip-ssl', is_flag=True, help='Skip SSL configuration and certificate generation when configuring Nginx')
@click.option('--alias', '-a', multiple=True, help='Additional domains that will redirect to the main domain')
@click.option('--prefix', '-p', help='Custom database prefix that will be used in the WordPress configuration')
def import_site(domain: str, archive:str, database_dump: str, skip_ssl: bool, alias: list[str], prefix: str|None) -> None:
    """Adds a new configured WordPress instance."""
    # TODO: We should validate that domain is actually a domain
    console = Console()

    if skip_ssl:
        console.print('Configuring HTTP-only site, this should only be used for testing purposes!', style='yellow')

    add_instance(domain, alias, skip_ssl, prefix, os.path.abspath(archive), os.path.abspath(database_dump))

@main.group('maintenance')
def maintenance() -> None:
    """Performs various maintenance-related tasks."""

@maintenance.command('update')
@click.argument('domain', default='all', help='Domain to update, if not set or set to `all`, it will update all domains plus additional services (Nginx and MariaDB, mainly).')
def update(domain: str) -> None:
    """Updates all images based on the configured tags."""
    update_containers(domain if domain != 'all' else None)

@maintenance.command('cleanup')
def cleanup() -> None:
    """Performs any cleanup task needed for maintentance."""
    perform_cleanup()

@maintenance.command('renew')
def renew() -> None:
    """Renews all certificates that need renewing via Certbot."""
    renew_certs()

if __name__ == '__main__':
    main()
