import docker
from rich.console import Console
from rich.progress import Progress

from containerized_wp_manager.list import instance_list


def renew_certs() -> None:
    console = Console()
    docker_client = docker.from_env()
    instances = instance_list()
    renewable_sites = sum(1 for x in instances if not x['external'] and not x['config']['http-only'])

    if 0 == renewable_sites:
        console.print('No sites have a renewable cert!', style='green')
        return

    with Progress() as progress:
        sites_task = progress.add_task('Updating sites...', total=renewable_sites)
        for instance in instances:
            # Ignore external and HTTP-only sites
            if instance['external'] or instance['config']['http-only']:
                continue

            docker_client.containers.run(
                image='certbot/certbot',
                name='cwpm-certbot',
                volumes=[
                    f'/opt/containerized-wp-manager/certbot/etc/{id}:/etc/letsencrypt:rw',
                    f'/opt/containerized-wp-manager/certbot/var/{id}:/var/lib/letsencrypt:rw',
                    f'/opt/containerized-wp-manager/certbot/log/{id}:/var/log/letsencrypt:rw',
                    f'/opt/containerized-wp-manager/sites/{id}:/var/www/html:rw'
                ],
                command=f'certonly renew --non-interactive --agree-tos --webroot -w /var/www/html -d {instance['config']['domain']}',
                auto_remove=True
            )

            progress.update(sites_task, advance=1)

    console.print('All certificates renewed successfully!', style='green')
