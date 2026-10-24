"""Проверки рисков потери данных; запуск: python -m unittest -v."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import pandas as pd
from prepare_data import COLS, FLAGS, exact_integer, prepare, read_prepared, sha256


class CleaningTests(unittest.TestCase):
    def test_exact_integers(self):
        self.assertEqual(exact_integer('9007199254740993.0'), 9007199254740993)
        for value in ['NaN', 'Infinity', '1.5', '-1', '9223372036854775808', 'abc']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                exact_integer(value)

    def sources(self, root):
        a = dict.fromkeys(COLS['companies'], '')
        a.update(SYNTHETIC_U='U_001', MAINOKVED_CODE='01.10', REVENUE_COMPANY='9007199254740993.0')
        a.update({c: '0.0' for c in FLAGS})
        b = dict(a, SYNTHETIC_U='U_2', REVENUE_COMPANY='100')
        c = dict(b, REVENUE_COMPANY='200')
        data = {
            'companies': pd.DataFrame([a, b, c]),
            'persons': pd.DataFrame([['F_001', ' U_001 ', 'Не определено', ''], ['F_001', 'U_9', 'Москва', 'Москва']], columns=COLS['persons']),
            'payments': pd.DataFrame([['U_2', 'U_001', '10.0', '1'], ['U_2', 'U_001', '10.0', '1'], ['U_001', 'U_001', '0', '0'], ['U_9', 'U_001', '', '2']], columns=COLS['payments'])
        }
        paths = {}
        for name, df in data.items():
            paths[name] = root / f'{name}.csv'
            df.to_csv(paths[name], sep=';', index=False)
        return paths

    def test_pipeline_and_repeatability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.sources(root)
            before = {k: sha256(p) for k, p in paths.items()}
            with contextlib.redirect_stdout(io.StringIO()):
                prepare(paths, root / 'one')
                prepare(paths, root / 'two')
            self.assertEqual(before, {k: sha256(p) for k, p in paths.items()})
            one = {p.name: sha256(p) for p in (root / 'one').iterdir()}
            two = {p.name: sha256(p) for p in (root / 'two').iterdir()}
            self.assertEqual(one, two)
            persons = read_prepared(root / 'one', 'person_links_prepared')
            self.assertEqual(persons.loc[0, 'SYNTHETIC_U'], 'U_001')
            self.assertEqual(persons.loc[0, 'SYNTHETIC_F'], 'F_001')
            self.assertTrue(pd.isna(persons.loc[0, 'CITY_NAME']))
            nodes = read_prepared(root / 'one', 'company_nodes').set_index('SYNTHETIC_U')
            self.assertEqual(nodes.loc['U_2', 'profile_status'], 'ambiguous')
            self.assertTrue(pd.isna(nodes.loc['U_2', 'REVENUE_COMPANY']))
            self.assertEqual(nodes.loc['U_9', 'profile_status'], 'missing')
            self.assertEqual(nodes.loc['U_001', 'MAINOKVED_CODE'], '01.10')
            self.assertEqual(nodes.loc['U_001', 'REVENUE_COMPANY'], 9007199254740993)
            payments = read_prepared(root / 'one', 'payments_prepared')
            self.assertEqual(len(payments), 4)
            self.assertEqual(payments.full_duplicate.sum(), 2)
            self.assertEqual(payments.self_payment.sum(), 1)
            self.assertTrue(payments.loc[2, 'pay_amt_zero'])
            self.assertTrue(pd.isna(payments.loc[3, 'PAY_AMT']))
            self.assertEqual(payments.loc[0, 'beneficiary_profile_status'], 'ambiguous')
            with self.assertRaises(ValueError):
                prepare(paths, root / 'one')

    def test_bad_source_produces_no_output(self):
        for field, value in [('PAY_AMT', '-1'), ('PAYER', ''), ('PAY_CNT', '1.2')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = self.sources(root)
                df = pd.read_csv(paths['payments'], sep=';', dtype=str, keep_default_na=False)
                df.loc[0, field] = value
                df.to_csv(paths['payments'], sep=';', index=False)
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                    prepare(paths, root / 'out')
                self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
