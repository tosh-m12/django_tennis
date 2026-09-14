from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class OrganizerAndAdminPathMigrationTests(TransactionTestCase):
    migrate_from = ("tennis", "0022_club_demo_seed_version")
    migrate_to = ("tennis", "0026_club_admin_path_token")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps

        Club = old_apps.get_model("tennis", "Club")
        Event = old_apps.get_model("tennis", "Event")
        self.club_id = Club.objects.create(
            name="既存クラブ",
            public_token="public-token-before-release",
            admin_token="admin-token-before-release",
        ).id
        self.event_id = Event.objects.create(
            club_id=self.club_id,
            title="既存の練習会",
            date="2026-09-01",
        ).id

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_existing_club_urls_and_event_survive_migration(self):
        Club = self.apps.get_model("tennis", "Club")
        Event = self.apps.get_model("tennis", "Event")

        club = Club.objects.get(pk=self.club_id)
        self.assertEqual(club.public_token, "public-token-before-release")
        self.assertEqual(club.admin_path_token, "public-token-before-release")
        self.assertEqual(club.admin_token, "admin-token-before-release")
        self.assertTrue(
            Event.objects.filter(
                pk=self.event_id,
                club_id=self.club_id,
                title="既存の練習会",
            ).exists()
        )
