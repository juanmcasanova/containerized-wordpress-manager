import click
from rich.console import Console

from containerized_wp_manager.add import add_instance
from containerized_wp_manager.check import check_and_print
from containerized_wp_manager.install import install_environment
from containerized_wp_manager.list import list_instances


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
def add(domain: str, skip_ssl: bool, alias: list[str]) -> None:
    """Adds a new configured WordPress instance."""
    # TODO: We should validate that domain is actually a domain
    console = Console()

    if skip_ssl:
        console.print('Configuring HTTP-only site, this should only be used for testing purposes!', style='yellow')

    add_instance(domain, alias, skip_ssl)

if __name__ == '__main__':
    main()
