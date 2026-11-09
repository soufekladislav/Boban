"""Guard against cross-IIFE drawer regressions."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class DrawerScopeTests(unittest.TestCase):
    def test_shared_renderer_export_and_import(self):
        src=(ROOT/'static/app.js').read_text(encoding='utf-8')
        self.assertIn('window.BobanChatUI = Object.freeze({renderAssistantBubble, chatTimeElement})',src)
        self.assertIn('const renderAssistantBubble=sharedChat?.renderAssistantBubble',src)
    def test_history_and_send_endpoints_shared(self):
        template=(ROOT/'templates/base.html').read_text(encoding='utf-8')
        self.assertIn("url_for('project_chat_recent'",template)
        self.assertIn("url_for('project_chat'",template)
        self.assertIn('091324',template)
