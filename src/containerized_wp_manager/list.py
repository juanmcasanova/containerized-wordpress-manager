import os

import click


def list_instances() -> None:
    for instance in os.listdir('/opt/wp-docker-manager/sites'):
        click.echo(click.style('Currently enabled sites:', bold=True))
        click.echo(f'- {instance}')
