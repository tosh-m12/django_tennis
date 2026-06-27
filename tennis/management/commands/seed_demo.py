from django.core.management.base import BaseCommand

from tennis.demo_seed import create_seeded_demo_club, sweep_stale_demo_clubs


class Command(BaseCommand):
    help = "デモクラブを1つ作成（動作確認用）。--sweep で無操作デモクラブの掃除のみ実行。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--sweep",
            action="store_true",
            help="新規作成せず、無操作で残っているデモクラブの掃除だけ行う。",
        )

    def handle(self, *args, **options):
        if options.get("sweep"):
            n = sweep_stale_demo_clubs()
            self.stdout.write(self.style.SUCCESS(f"swept stale demo clubs: {n}"))
            return

        club = create_seeded_demo_club()
        self.stdout.write(self.style.SUCCESS(
            f"demo club created: id={club.id} public_token={club.public_token}"
        ))
        self.stdout.write(f"member home: /c/{club.public_token}/")
        self.stdout.write(f"admin home:  /c/{club.public_token}/admin/{club.admin_token}/")
