import docker
from rich.progress import Progress


def perform_cleanup() -> None:
    docker_client = docker.from_env()

    with Progress() as progress:
        images_task = progress.add_task('Pruning images...', total=2)
        docker_client.images.prune(filters={'dangling': False})
        progress.update(images_task, advance=1)
        docker_client.images.prune_builds()
        progress.update(images_task, advance=1)

        containers_task = progress.add_task('Pruning containers...', total=1)
        docker_client.containers.prune()
        progress.update(containers_task, advance=1)

        networks_task = progress.add_task('Pruning networks...', total=1)
        docker_client.networks.prune()
        progress.update(networks_task, advance=1)
