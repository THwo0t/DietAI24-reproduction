import unittest

from analyze_h import mass_comparison, summarize


def item(identifier, grams):
    return {'ingredient_id': identifier, 'grams': grams}


class MassDiagnosticTests(unittest.TestCase):
    def test_duplicate_ids_merged_before_overlap(self):
        r = mass_comparison([item('a', 70), item('a', 60)], [item('a', 100)])
        self.assertEqual(r['exact_id_mass_overlap_g'], 100)
        self.assertEqual(r['matched_id_over_mass_g'], 30)

    def test_unknown_not_assumed_correct(self):
        r = mass_comparison([item(None, 100)], [item('a', 100)])
        self.assertEqual(r['absolute_total_mass_error_g'], 0)
        self.assertEqual(r['exact_id_mass_overlap_g'], 0)
        self.assertEqual(r['unpaired_mass_l1_g'], 200)

    def test_presence_not_quantity_and_cancellation(self):
        r = mass_comparison([item('a', 20), item('c', 80)], [item('a', 70), item('b', 30)])
        self.assertEqual(r['reference_mass_with_present_id_g'], 70)
        self.assertEqual(r['exact_id_mass_overlap_g'], 20)
        self.assertEqual(r['omitted_reference_id_mass_g'], 30)
        self.assertEqual(r['extra_known_id_mass_g'], 80)
        self.assertEqual(r['matched_id_under_mass_g'], 50)
        self.assertEqual(r['unpaired_mass_l1_g'], 160)
        self.assertEqual(r['absolute_total_mass_error_g'], 0)

    def test_micro_and_mean_keep_all_rows_and_differ(self):
        rows = [mass_comparison([item('a', 900)], [item('a', 900)]),
                mass_comparison([item(None, 100)], [item('b', 100)])]
        s = summarize(rows)
        self.assertEqual(s['n'], 2)
        self.assertEqual(s['micro_rates']['unknown_predicted_mass_fraction'], .1)
        self.assertEqual(s['mean_image_rates']['unknown_predicted_mass_fraction'], .5)

    def test_nonpositive_nonfinite_rejected(self):
        for grams in (0, -1, float('nan'), float('inf')):
            with self.subTest(grams=grams), self.assertRaises(ValueError):
                mass_comparison([item('a', grams)], [item('a', 1)])


if __name__ == '__main__':
    unittest.main()
