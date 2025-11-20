"""Unit tests for deepagents_cli.skills.commands."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from deepagents_cli.skills.commands import (
    _create,
    _info,
    _list,
    _validate_skill_name,
    _validate_skill_path,
)


@pytest.fixture
def mock_console():
    with patch("deepagents_cli.skills.commands.console") as mock:
        yield mock


def test_validate_skill_name():
    """Test skill name validation."""
    # Valid names
    assert _validate_skill_name("my-skill")[0] is True
    assert _validate_skill_name("skill_123")[0] is True
    
    # Invalid names
    assert _validate_skill_name("")[0] is False
    assert _validate_skill_name("skill/name")[0] is False
    assert _validate_skill_name("../skill")[0] is False
    assert _validate_skill_name("skill name")[0] is False  # Spaces not allowed


def test_validate_skill_path():
    """Test skill path validation."""
    base_dir = Path("/home/user/.deepagents/agent/skills")
    
    # Valid path
    assert _validate_skill_path(base_dir / "my-skill", base_dir)[0] is True
    
    # Invalid path (outside base)
    assert _validate_skill_path(Path("/etc/passwd"), base_dir)[0] is False
    assert _validate_skill_path(base_dir.parent, base_dir)[0] is False


def test_list_skills(mock_console):
    """Test listing skills."""
    with patch("deepagents_cli.skills.commands.Path.exists", return_value=True), \
         patch("deepagents_cli.skills.commands.Path.iterdir", return_value=[MagicMock()]), \
         patch("deepagents_cli.skills.commands.list_skills") as mock_list:
        
        # Case 1: Skills found
        mock_list.return_value = [
            {"name": "skill1", "description": "desc1", "path": "/path/to/skill1/SKILL.md"}
        ]
        _list()
        mock_console.print.assert_called()
        assert "skill1" in str(mock_console.print.call_args_list)
        
        # Case 2: No skills found
        mock_list.return_value = []
        _list()
        assert "No valid skills found" in str(mock_console.print.call_args_list)


def test_create_skill(mock_console):
    """Test creating a skill."""
    with patch("deepagents_cli.skills.commands.Path.exists", return_value=False), \
         patch("deepagents_cli.skills.commands.Path.mkdir") as mock_mkdir, \
         patch("deepagents_cli.skills.commands.Path.write_text") as mock_write:
        
        # Create valid skill
        _create("new-skill")
        
        mock_mkdir.assert_called_once()
        mock_write.assert_called_once()
        assert "created successfully" in str(mock_console.print.call_args_list)


def test_create_skill_invalid(mock_console):
    """Test creating invalid skill."""
    _create("invalid name")
    assert "Invalid skill name" in str(mock_console.print.call_args_list)


def test_info_skill(mock_console):
    """Test showing skill info."""
    with patch("deepagents_cli.skills.commands.list_skills") as mock_list, \
         patch("deepagents_cli.skills.commands.Path") as MockPath:
        
        # Setup mock path instance
        mock_path_instance = MagicMock()
        mock_path_instance.read_text.return_value = "Skill Content"
        mock_path_instance.parent.iterdir.return_value = []
        MockPath.return_value = mock_path_instance
        
        # Skill exists
        mock_list.return_value = [
            {"name": "skill1", "description": "desc1", "path": "/path/to/skill1/SKILL.md"}
        ]
        
        _info("skill1")
        assert "Skill: skill1" in str(mock_console.print.call_args_list)
        assert "Skill Content" in str(mock_console.print.call_args_list)
        
        # Skill does not exist
        _info("unknown")
        assert "not found" in str(mock_console.print.call_args_list)
