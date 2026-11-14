import unittest
from goal_first import prioritized_items, readiness_items, selected_work


class GoalFirstTests(unittest.TestCase):
    def test_missing_records_are_not_zero_sales(self):
        r = readiness_items(3, {'business_goal': 'Zvýšit počet objednávek', 'primary_conversion': 'purchase'},
                            {'ga4': 'connected', 'search_console': 'connected'},
                            {'ga4': {}, 'search_console': {}}, True, False)
        self.assertIn('Doložit skutečné konverze', [x['title'] for x in r])
        self.assertIn('Neznamená to nula', str(r))
        self.assertIn('Ověřit načtení dat GA4', [x['title'] for x in r])

    def test_unfocused_audits_do_not_outrank_business_growth(self):
        items = [{'title': 'Opravit 700 ALT', 'kind': 'execution', 'priority': 100},
                 {'title': 'Zvýšit CTR kola', 'kind': 'growth', 'priority': 82},
                 {'title': 'Schválit návrhy', 'kind': 'approval', 'priority': 96}]
        r = prioritized_items(items, {'business_goal': 'Prodej kol', 'priority_topics': ['kola']})
        self.assertEqual(r[0]['kind'], 'approval')
        self.assertEqual(r[1]['kind'], 'growth')

    def test_no_goal_means_no_automatic_seo_work(self):
        plan = {'strategy': {'business_goal': ''},
                'items': [{'kind': 'execution', 'can_prepare': True, 'issue_ids': [2]}]}
        self.assertEqual(selected_work(plan), (set(), set()))
        self.assertEqual(prioritized_items(plan['items'], plan['strategy']), [])

    def test_operator_is_scoped_to_selected_tasks(self):
        plan = {'strategy': {'business_goal': 'Poptávky'},
                'items': [{'kind': 'execution', 'can_prepare': True, 'issue_ids': [3, 9]},
                          {'kind': 'growth', 'can_prepare': True, 'primary_page': 'https://example.com/auto/'}]}
        self.assertEqual(selected_work(plan), ({3, 9}, {'https://example.com/auto'}))

    def test_connected_is_not_verified(self):
        r = readiness_items(1, {'business_goal': 'Objednávky', 'primary_conversion': 'purchase'},
                            {'ga4': 'connected', 'search_console': 'connected'}, {}, False, False)
        self.assertIn('stav připojení', str(r).lower())
        self.assertTrue(all(x['can_prepare'] is False for x in r))


if __name__ == '__main__':
    unittest.main()
