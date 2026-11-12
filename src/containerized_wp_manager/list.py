import os

import yaml
from rich.console import Console
from rich.table import Table
from rich.text import Text


def instance_list() -> list[dict[str, str]]:
    instances = []
    for instance in os.listdir('/opt/containerized-wp-manager/sites'):
        if os.path.isfile(f'/opt/containerized-wp-manager/sites/{instance}/.cwpm-config.yaml'):
            with open(f'/opt/containerized-wp-manager/sites/{instance}/.cwpm-config.yaml', 'r') as config_file:
                config = yaml.load(config_file, Loader=yaml.Loader)
                instances.append({'id': instance, 'external': False, 'alias': False, 'config': config})
        elif os.path.isfile(f'/opt/containerized-wp-manager/sites/{instance}/.cwpm-alias.yaml'):
            with open(f'/opt/containerized-wp-manager/sites/{instance}/.cwpm-alias.yaml', 'r') as config_file:
                config = yaml.load(config_file, Loader=yaml.Loader)
                instances.append({'id': instance, 'external': False, 'alias': True, 'config': config})
        else:
            # This means we have nothing to do with this site, list it as an external site
            instances.append({'id': instance, 'external': True})

    return instances

def list_instances() -> None:
    table = Table(title="Wordpress instances")
    table.add_column('ID')
    table.add_column('URL')
    table.add_column('HTTP only')

    external_table = Table(title="External sites")
    external_table.add_column('ID')
    external_table.add_column('Full path')

    no_text = Text('No', style='green')
    yes_text = Text('Yes', style='red')

    for instance in instance_list():
        if instance['external']:
            external_table.add_row(instance['id'], f'/opt/containerized-wp-manager/sites/{instance['id']}')
        elif instance['alias']:
            url = f'http{'s' if not instance['config']['http-only'] else ''}://{instance['config']['domain']}'
            main_url = f'http{'s' if not instance['config']['http-only'] else ''}://{instance['config']['main-domain']}'
            table.add_row(Text(f'{instance['id']} (Alias for {main_url})', style='orange1'), f'[link={url}]{url}[/link]', yes_text if instance['config']['http-only'] else no_text)
        else:
            url = f'http{'s' if not instance['config']['http-only'] else ''}://{instance['config']['domain']}'
            table.add_row(Text(instance['id'], style='cyan'), f'[link={url}]{url}[/link]', yes_text if instance['config']['http-only'] else no_text)

    console = Console()
    console.print(table)
    if external_table.row_count:
        console.print(external_table)
