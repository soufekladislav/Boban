import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class MerchantRegistrationCallbackTests(unittest.TestCase):
    def test_admin_identity_comparison_normalizes_type(self):
        tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf8'))
        fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == '_admin_merchant_registration_callback')
        source = ast.get_source_segment((ROOT / 'app.py').read_text(encoding='utf8'), fn)
        self.assertIn("str(pending.get('admin_id') or '') != str(current_user.id)", source)
        self.assertNotIn("int(pending.get('admin_id') or 0)!=current_user.id", source)

    def test_users_id_is_string(self):
        tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf8'))
        fn = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'User')
        source = ast.get_source_segment((ROOT / 'app.py').read_text(encoding='utf8'), fn)
        self.assertIn('self.id = str(row["id"])', source)
