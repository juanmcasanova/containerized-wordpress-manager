import click

from containerized_wp_manager.add import add_instance
from containerized_wp_manager.check import check_environment
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
    check_environment()

@main.command('install')
def install() -> None:
    """
    Configures everything missing to ensure the environment is right.
    """
    install_environment()

@main.command('list')
def list() -> None:
    """
    Lists all currently available instances.
    """
    list_instances()

@main.command('add')
@click.argument('id', help='Unique identifier for the new instance')
@click.argument('domain', help='Domain where the new instance will be served at')
def add(id: str, domain: str) -> None:
    """
    Adds a new configured WordPress instance.
    """
    # TODO: wordpress is a reserved name due to how the WordPress ZIP release is, we should validate it
    add_instance(id, domain)

if __name__ == '__main__':
    main()
