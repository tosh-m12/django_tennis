from django.core.management.base import BaseCommand

from tennis.demo_seed import get_or_create_demo_club, reseed_demo_club


class Command(BaseCommand):
    help = "デモクラブ（/demo）を初期化（ベースラインへリセット）する。毎日のリセットにも使える。"

    def handle(self, *args, **options):
        club = get_or_create_demo_club()
        reseed_demo_club(club)
        club.refresh_from_db()
        url = f"/c/{club.public_token}/"
        self.stdout.write(self.style.SUCCESS(
            f"demo seeded: club_id={club.id} public_token={club.public_token}"
        ))
        self.stdout.write(f"member home: {url}")
        self.stdout.write(f"admin home:  /c/{club.public_token}/admin/{club.admin_token}/")
