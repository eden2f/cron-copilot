"""脚本管理测试 — ScriptManager 和 VersionManager."""

import os
import pytest

from croncopilot.config.schema import ScriptConfig
from croncopilot.scripts.manager import ScriptManager
from croncopilot.scripts.version import VersionManager, ScriptMetadata


class TestScriptManager:
    """测试 ScriptManager."""

    def _make_manager(self, tmp_dir, tmp_db):
        script_dir = os.path.join(tmp_dir, "scripts")
        version_dir = os.path.join(tmp_dir, "versions")
        os.makedirs(script_dir, exist_ok=True)
        config = ScriptConfig(
            script_dir=script_dir,
            version_dir=version_dir,
            max_versions=3,
        )
        return ScriptManager(config=config, db_manager=tmp_db), script_dir, version_dir

    def _create_script(self, path, content="print('hello')\n"):
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_register_script(self, tmp_dir, tmp_db):
        """注册脚本，元数据正确保存."""
        mgr, script_dir, _ = self._make_manager(tmp_dir, tmp_db)
        script_path = self._create_script(os.path.join(script_dir, "my_script.py"))

        meta = mgr.register(script_path, name="my_script", author="tester", category="util")
        assert meta.name == "my_script"
        assert meta.author == "tester"
        assert meta.category == "util"
        assert meta.file_hash != ""

        # Can retrieve info
        info = mgr.get_info("my_script")
        assert info is not None
        assert info.name == "my_script"

    def test_unregister_script(self, tmp_dir, tmp_db):
        """注销脚本."""
        mgr, script_dir, _ = self._make_manager(tmp_dir, tmp_db)
        script_path = self._create_script(os.path.join(script_dir, "unreg.py"))
        mgr.register(script_path, name="unreg")

        mgr.unregister("unreg")
        assert mgr.get_info("unreg") is None

    def test_register_external_script(self, tmp_dir, tmp_db):
        """注册外部路径脚本（自动复制到 script_dir）."""
        mgr, script_dir, _ = self._make_manager(tmp_dir, tmp_db)
        # Create script outside script_dir
        external_dir = os.path.join(tmp_dir, "external")
        os.makedirs(external_dir, exist_ok=True)
        ext_script = self._create_script(os.path.join(external_dir, "ext.py"), "print('external')\n")

        meta = mgr.register(ext_script, name="ext_script")
        # Script should be copied to script_dir
        assert os.path.isfile(os.path.join(script_dir, "ext.py"))
        assert meta.path == os.path.join(script_dir, "ext.py")

    def test_script_version_backup(self, tmp_dir, tmp_db):
        """脚本变更时自动备份."""
        mgr, script_dir, version_dir = self._make_manager(tmp_dir, tmp_db)
        script_path = self._create_script(os.path.join(script_dir, "versioned.py"), "v1\n")
        mgr.register(script_path, name="versioned")

        # Modify script and update
        self._create_script(script_path, "v2\n")
        mgr.update_script("versioned", new_path=script_path)

        versions = mgr.get_versions("versioned")
        # Should have at least the initial version backup
        assert len(versions) >= 1

    def test_version_cleanup(self, tmp_dir, tmp_db):
        """超出 max_versions 的旧版本被清理."""
        mgr, script_dir, version_dir = self._make_manager(tmp_dir, tmp_db)
        script_path = self._create_script(os.path.join(script_dir, "cleanup.py"), "v0\n")
        mgr.register(script_path, name="cleanup")

        # Create many versions (max_versions=3)
        for i in range(5):
            self._create_script(script_path, f"v{i + 1}\n")
            mgr.update_script("cleanup", new_path=script_path)

        versions = mgr.get_versions("cleanup")
        assert len(versions) <= 3

    def test_list_versions(self, tmp_dir, tmp_db):
        """列出版本历史."""
        mgr, script_dir, _ = self._make_manager(tmp_dir, tmp_db)
        script_path = self._create_script(os.path.join(script_dir, "lv.py"), "v1\n")
        mgr.register(script_path, name="lv")

        versions = mgr.get_versions("lv")
        assert isinstance(versions, list)
        # At least 1 version from initial registration
        assert len(versions) >= 1
        assert "version_path" in versions[0]
        assert "timestamp" in versions[0]

    def test_restore_version(self, tmp_dir, tmp_db):
        """恢复到历史版本."""
        mgr, script_dir, _ = self._make_manager(tmp_dir, tmp_db)
        script_path = self._create_script(os.path.join(script_dir, "restore.py"), "original\n")
        mgr.register(script_path, name="restore")

        # Get version list (initial backup)
        versions_before = mgr.get_versions("restore")
        assert len(versions_before) >= 1
        first_version = versions_before[0]["version_path"]

        # Modify script
        self._create_script(script_path, "modified\n")
        mgr.update_script("restore", new_path=script_path)

        # Restore to first version
        result = mgr.restore_version("restore", first_version)
        assert result is True

        # Verify content is restored
        with open(script_path, "r") as f:
            content = f.read()
        assert content.strip() == "original"

    def test_validate_script(self, tmp_dir, tmp_db):
        """有效和无效脚本的验证."""
        mgr, script_dir, _ = self._make_manager(tmp_dir, tmp_db)

        # Valid script
        valid = self._create_script(os.path.join(script_dir, "valid.py"), "x = 1\n")
        ok, msg = mgr.validate_script(valid)
        assert ok is True
        assert "valid" in msg.lower()

        # Invalid script (syntax error)
        invalid = self._create_script(os.path.join(script_dir, "invalid.py"), "def foo(\n")
        ok, msg = mgr.validate_script(invalid)
        assert ok is False
        assert "syntax" in msg.lower() or "error" in msg.lower()

        # Non-existent script
        ok, msg = mgr.validate_script("/nonexistent/path.py")
        assert ok is False

    def test_scan_directory(self, tmp_dir, tmp_db):
        """扫描未注册的脚本."""
        mgr, script_dir, _ = self._make_manager(tmp_dir, tmp_db)

        # Create some scripts — register only one
        self._create_script(os.path.join(script_dir, "registered.py"))
        self._create_script(os.path.join(script_dir, "unregistered1.py"))
        self._create_script(os.path.join(script_dir, "unregistered2.py"))

        mgr.register(os.path.join(script_dir, "registered.py"), name="registered")

        unregistered = mgr.scan_directory()
        # Should find at least 2 unregistered scripts
        names = [os.path.basename(p) for p in unregistered]
        assert "unregistered1.py" in names
        assert "unregistered2.py" in names
        assert "registered.py" not in names

    def test_list_scripts_by_category(self, tmp_dir, tmp_db):
        """按分类过滤."""
        mgr, script_dir, _ = self._make_manager(tmp_dir, tmp_db)

        s1 = self._create_script(os.path.join(script_dir, "cat_a.py"), "# a\n")
        s2 = self._create_script(os.path.join(script_dir, "cat_b.py"), "# b\n")
        s3 = self._create_script(os.path.join(script_dir, "cat_c.py"), "# c\n")

        mgr.register(s1, name="cat_a", category="data")
        mgr.register(s2, name="cat_b", category="data")
        mgr.register(s3, name="cat_c", category="ops")

        data_scripts = mgr.list_scripts(category="data")
        assert len(data_scripts) == 2
        assert all(s.category == "data" for s in data_scripts)

        ops_scripts = mgr.list_scripts(category="ops")
        assert len(ops_scripts) == 1

        all_scripts = mgr.list_scripts()
        assert len(all_scripts) == 3
