from .test_project_base import TestProjectCommon


class TestProjectConfig(TestProjectCommon):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.Settings = cls.env["res.config.settings"]
        cls.user_settings_project_manager = cls.env[
            "res.users.settings"
        ]._get_or_create_for_user(cls.user_projectmanager)
        cls.user_settings_project_user = cls.env[
            "res.users.settings"
        ]._get_or_create_for_user(cls.user_projectuser)

    def test_project_stages_feature_enable_views(self) -> None:
        self.Settings.create({"group_project_stages": True}).execute()
        menu_ids = {
            self.env.ref("project.menu_projects").id,
            self.env.ref("project.menu_projects_config").id,
        }
        menu_loaded = set(self.env["ir.ui.menu"]._load_menus_blacklist())
        self.assertTrue(
            menu_ids.issubset(menu_loaded),
            "The menu project and menu projects config should be loaded",
        )

    def test_copy_project_manager_embedded_config_as_default(self) -> None:
        project = self.env["project.project"].create(
            {
                "name": "Test Project",
                "user_id": self.user_projectmanager.id,
            }
        )
        project_action = self.env["ir.actions.act_window"].create(
            {
                "name": "Test Project Action",
                "res_model": "project.project",
            }
        )
        project_manager_config = self.env["res.users.settings.embedded.action"].create(
            {
                "user_setting_id": self.user_settings_project_manager.id,
                "action_id": project_action.id,
                "res_model": "project.project",
                "res_id": project.id,
                "embedded_actions_order": "false,3,2,1",
                "embedded_actions_visibility": "1,2,3",
                "embedded_visibility": True,
            }
        )

        self.assertFalse(self.user_settings_project_user.embedded_actions_config_ids)
        project_user_config = self.user_settings_project_user.with_context(
            res_model="project.project",
            res_id=project.id,
        ).get_embedded_actions_settings()
        self.assertDictEqual(
            project_user_config[f"{project_action.id}+{project.id}"],
            {
                "embedded_actions_order": [False, 3, 2, 1],
                "embedded_actions_visibility": [1, 2, 3],
                "embedded_visibility": True,
            },
        )

        project_user_config = (
            self.user_settings_project_user.embedded_actions_config_ids
        )
        self.assertEqual(
            len(project_user_config),
            1,
            "There should be one embedded action setting created.",
        )
        self.assertEqual(
            project_user_config.action_id,
            project_manager_config.action_id,
            "The action should match the one set in the project manager config.",
        )
        self.assertEqual(
            project_user_config.res_id,
            project_manager_config.res_id,
            "The res_id should match the one set in the project manager config.",
        )
        self.assertEqual(
            project_user_config.res_model,
            project_manager_config.res_model,
            "The res_model should match the one set in the project manager config.",
        )
        self.assertEqual(
            project_user_config.embedded_actions_order,
            project_manager_config.embedded_actions_order,
            "The embedded actions order should match the one set in the project manager config.",
        )
        self.assertEqual(
            project_user_config.embedded_actions_visibility,
            project_manager_config.embedded_actions_visibility,
            "The embedded actions visibility should match the one set in the project manager config.",
        )
        self.assertEqual(
            project_user_config.embedded_visibility,
            project_manager_config.embedded_visibility,
            "The embedded visibility should match the one set in the project manager config.",
        )

    def test_no_copy_project_manager_embedded_config_as_default(self) -> None:
        project = self.env["project.project"].create(
            {
                "name": "Test Project",
                "user_id": self.user_projectmanager.id,
            }
        )
        project_action = self.env["ir.actions.act_window"].create(
            {
                "name": "Test Project Action",
                "res_model": "project.project",
            }
        )
        self.env["res.users.settings.embedded.action"].create(
            {
                "user_setting_id": self.user_settings_project_manager.id,
                "action_id": project_action.id,
                "res_model": "project.project",
                "res_id": project.id,
                "embedded_actions_order": "false,3,2,1",
                "embedded_actions_visibility": "1,2,3",
                "embedded_visibility": True,
            }
        )
        user_config = self.env["res.users.settings.embedded.action"].create(
            {
                "user_setting_id": self.user_settings_project_user.id,
                "action_id": project_action.id,
                "res_model": "project.project",
                "res_id": project.id,
                "embedded_actions_order": "false,1,2,3",
                "embedded_actions_visibility": "2,3",
                "embedded_visibility": False,
            }
        )
        self.assertEqual(
            len(self.user_settings_project_user.embedded_actions_config_ids), 1
        )

        project_user_config = self.user_settings_project_user.with_context(
            res_model="project.project",
            res_id=project.id,
        ).get_embedded_actions_settings()
        self.assertDictEqual(
            project_user_config[f"{project_action.id}+{project.id}"],
            {
                "embedded_actions_order": [False, 1, 2, 3],
                "embedded_actions_visibility": [2, 3],
                "embedded_visibility": False,
            },
        )

        project_user_config = (
            self.user_settings_project_user.embedded_actions_config_ids
        )
        self.assertEqual(
            len(project_user_config),
            1,
            "There should still be only one embedded action setting created.",
        )
        self.assertEqual(
            project_user_config,
            user_config,
            "The existing user config should be unchanged.",
        )
