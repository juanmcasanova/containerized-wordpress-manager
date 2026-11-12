import docker
from rich.console import Console
from rich.progress import Progress

from containerized_wp_manager.add import start_container
from containerized_wp_manager.install import (
    MARIADB_TAG,
    NGINX_TAG,
    build_php_image,
    start_mariadb_container,
    start_nginx_container,
)
from containerized_wp_manager.list import instance_list


def update_containers(domain: str|None) -> None:
    """Updates the managed Docker containers."""
    docker_client = docker.from_env()

    with Progress() as progress:
        # Update MariaDB and Nginx Only when there is no specific domain passed
        if domain is None:
            nginx_task = progress.add_task('Updating Nginx container...', total=100)
            nginx_container = docker_client.containers.list(filters={'name': 'cwpm-nginx'}, all=True)[0]
            registry_nginx = docker_client.images.get_registry_data(f'nginx:{NGINX_TAG}')

            if nginx_container.image is None or registry_nginx.id != nginx_container.image.id:
                # Remove the container
                nginx_container.stop()
                nginx_container.remove()

                # And recreate it (pulling the new image)
                start_nginx_container(docker_client)
            progress.update(nginx_task, advance=100)

            mariadb_task = progress.add_task('Updating MariaDB container...', total=100)
            mariadb_container = docker_client.containers.list(filters={'name': 'cwpm-mariadb'}, all=True)[0]
            registry_mariadb = docker_client.images.get_registry_data(f'mariadb:{MARIADB_TAG}')

            if mariadb_container.image is None or registry_mariadb.id != mariadb_container.image.id:
                # Remove the container
                mariadb_container.stop()
                mariadb_container.remove()

                # And recreate it (pulling the new image)
                start_mariadb_container(docker_client)
                # TODO: Should we execute mariadb-upgrade after updating the image?
            progress.update(mariadb_task, advance=100)

    console = Console()
    console.print('Starting the PHP image build...')
    # There seems to be no way of knowing which base image was used, so we always have to build
    build_php_image()

    # Again, we cannot know if the image needed to be rebuilt, so we have to always update the containers
    if domain is None:
        # Recreate all sites with the new image
        instances = instance_list()
        with Progress() as progress:
            sites_task = progress.add_task('Updating sites...', total=sum(1 for x in instances if not x['alias'] and not x['external']))
            for instance in instances:
                # Ignore aliases or external sites as those cannot be autoupdated (aliases don't really have a container, external sites are unknown)
                if instance['alias'] or instance['external']:
                    continue

                instance_container = docker_client.containers.list(filters={'name': f'cwpm-{instance['id']}'})[0]
                instance_container.stop()
                instance_container.remove()
                start_container(instance['id'], docker_client)
                progress.update(sites_task, advance=1)
    else:
        with Progress() as progress:
            sites_task = progress.add_task('Updating site...', total=100)

            instance_container = docker_client.containers.list(filters={'name': f'cwpm-{domain}'})[0]
            instance_container.stop()
            instance_container.remove()
            start_container(domain, docker_client)
            progress.update(sites_task, advance=100)

    console.print('Everything was updated successfully!', style='green')
