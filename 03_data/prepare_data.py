#!/usr/bin/env python3
"""L03: воспроизводимая подготовка трёх CSV; Python 3.10+, pandas 2.2.x.
python prepare_data.py --persons raw/person_links.csv --companies raw/companies.csv --payments raw/payments.csv --out processed
"""
import argparse
import csv
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile

import pandas as pd

VERSION = '1.0.0'
FLAGS = ['NEGATIVEMARK', 'CL_PRODUCT_RKO_MARK', 'CL_PRODUCT_GAR_MARK', 'CL_PRODUCT_LOA_MARK', 'CL_PRODUCT_LEA_MARK', 'CL_PRODUCT_DEP_MARK', 'CL_PRODUCT_ZPP_MARK', 'FTS_FLAG', 'FACTORING_MARK']
COMPANY_COLS = ['SYNTHETIC_U', 'ORG_TYPE', 'OKFS_NAME', 'COMPANY_AGE_YEARS_GRADATION', 'ECO_MARK_LABEL', 'MAINOKVED_CODE', 'MAINOKVED_NAME', 'NEGATIVEMARK', 'AMOUNT_WORKERS_FNS_GRADATION', 'AMOUNT_WORKERS_SPARK_GRADATION', 'CL_TYPE', 'CL_PRODUCT_RKO_MARK', 'CL_PRODUCT_GAR_MARK', 'CL_PRODUCT_LOA_MARK', 'CL_PRODUCT_LEA_MARK', 'CL_PRODUCT_DEP_MARK', 'CL_PRODUCT_ZPP_MARK', 'FTS_FLAG', 'FTS_COUNTRY_NAME', 'FACTORING_MARK', 'REVENUE_COMPANY', 'GROUP_ID', 'CITY', 'REGION']
COLS = {'persons': ['SYNTHETIC_F', 'SYNTHETIC_U', 'CITY_NAME', 'RC_NAME'], 'companies': COMPANY_COLS, 'payments': ['BENEFICIARY', 'PAYER', 'PAY_AMT', 'PAY_CNT']}
MARKERS = {'CITY_NAME': {'Неопределенный город', 'Не определено'}, 'RC_NAME': {'ИНН не определён', 'Не определено'}}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def exact_integer(value):
    """Без промежуточного float, округления и потери разрядов."""
    try:
        d = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f'Некорректное число: {value!r}') from exc
    require(d.is_finite() and d == d.to_integral_value(), f'Ожидалось конечное целое: {value!r}')
    require(0 <= d <= 9223372036854775807, f'Число вне диапазона неотрицательных Int64: {value!r}')
    return int(d)


def total(series):
    # Python int не переполняется при суммировании большого числа Int64.
    return sum(int(v) for v in series.dropna())


def json_write(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def csv_write(df, path):
    path = Path(path)
    if path.suffix == '.gz':
        with path.open('wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as z:
                with io.TextIOWrapper(z, encoding='utf-8', newline='') as f:
                    df.to_csv(f, index=False, lineterminator='\n', na_rep='')
    else:
        df.to_csv(path, index=False, encoding='utf-8', lineterminator='\n', na_rep='')


def read_prepared(directory, name):
    """Восстановить все типы из schema.json, включая nullable boolean."""
    directory = Path(directory)
    types = json.loads((directory / 'schema.json').read_text(encoding='utf-8'))[name]
    bools = [c for c, t in types.items() if t in ('bool', 'boolean')]
    dtypes = {c: ('string' if c in bools else t) for c, t in types.items()}
    df = pd.read_csv(directory / f'{name}.csv.gz', dtype=dtypes, keep_default_na=False, na_values=[''])
    for c in bools:
        require(df[c].dropna().isin(['True', 'False']).all(), f'Некорректный boolean: {c}')
        df[c] = df[c].map({'True': True, 'False': False}).astype(types[c])
    return df


def load_source(name, path, changes):
    # Строгая структура CSV: ни пропуска плохих строк, ни молчаливого сдвига полей.
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f, delimiter=';', strict=True)
        header = next(reader)
        require(len(header) == len(set(header)) and set(header) == set(COLS[name]), f'{name}: неожиданные колонки {header}')
        records = 0
        for record_no, row in enumerate(reader, 2):
            require(len(row) == len(header), f'{name}: запись {record_no}, неверное число полей')
            records += 1
    raw = pd.read_csv(path, sep=';', encoding='utf-8-sig', dtype='string', keep_default_na=False, skip_blank_lines=False)
    require(len(raw) == records and records > 0, f'{name}: пустой или некорректный CSV')
    df = raw.copy()
    df.insert(0, 'source_row', pd.Series(range(2, len(df) + 2), dtype='Int64'))
    changed = pd.Series(False, index=df.index)
    for c in raw.columns:
        old = raw[c]
        stripped = old.str.strip()
        markers = stripped.isin(MARKERS.get(c, set())) if name == 'persons' else pd.Series(False, index=df.index)
        blank = stripped.eq('')
        df[c] = stripped.mask(blank | markers)
        modified = old.ne(df[c].fillna('')) | blank | markers
        changed |= modified
        changes.append({'table': name, 'field': c, 'rule': 'strip_and_missing', 'trimmed': int(old.ne(stripped).sum()), 'empty_to_na': int(blank.sum()), 'marker_to_na': int(markers.sum()), 'changed_cells': int(modified.sum())})
    ids = {'persons': {'SYNTHETIC_F': r'F_\d+', 'SYNTHETIC_U': r'U_\d+'}, 'payments': {'PAYER': r'U_\d+', 'BENEFICIARY': r'U_\d+'}, 'companies': {'SYNTHETIC_U': r'U_\d+'}}[name]
    for c, pattern in ids.items():
        valid = df[c].str.fullmatch(pattern).fillna(False)
        require(valid.all(), f'{name}.{c}: некорректные/пустые ID в source_row={df.loc[~valid, "source_row"].head(10).tolist()}')
    numeric = {'persons': [], 'payments': ['PAY_AMT', 'PAY_CNT'], 'companies': FLAGS + ['REVENUE_COMPANY']}[name]
    for c in numeric:
        old = df[c].copy()
        mapping = {v: exact_integer(v) for v in old.dropna().unique()}
        df[c] = pd.Series([pd.NA if pd.isna(v) else mapping[v] for v in old], index=df.index, dtype='Int64')
        if c in FLAGS:
            require(df[c].dropna().isin([0, 1]).all(), f'{name}.{c}: флаг должен быть 0/1/NA')
            df[c] = df[c].astype('Int8')
        modified = old.fillna('').ne(df[c].astype('string').fillna(''))
        changed |= modified
        changes.append({'table': name, 'field': c, 'rule': 'exact_integer', 'trimmed': 0, 'empty_to_na': 0, 'marker_to_na': 0, 'changed_cells': int(modified.sum())})
    df['full_duplicate'] = raw.duplicated(keep=False).astype('boolean')
    df['normalized_duplicate'] = df.duplicated(list(raw.columns), keep=False).astype('boolean')
    stats = {'rows_in': len(raw), 'rows_out': len(df), 'rows_removed': 0, 'rows_with_value_or_missing_changes': int(changed.sum()), 'full_duplicate_extra_rows': int(raw.duplicated().sum()), 'normalized_duplicate_extra_rows': int(df.duplicated(list(raw.columns)).sum())}
    controls = {c: sum(exact_integer(v.strip()) for v in raw[c] if v.strip()) for c in numeric if c not in FLAGS}
    return df, stats, controls


def prepare(inputs, out):
    inputs = {k: Path(v).resolve() for k, v in inputs.items()}
    out = Path(out).resolve()
    require(not out.exists() or not any(out.iterdir()), 'Выходная папка уже содержит файлы. Укажите новую папку; исходники не перезаписываются.')
    for path in inputs.values():
        require(path.is_file(), f'Не найден исходный файл: {path}')
        require(out not in path.parents, 'Исходный CSV не должен находиться в выходной папке.')
    fingerprints = {k: sha256(v) for k, v in inputs.items()}
    frames, stats, controls, changes = {}, {}, {}, []
    for name, path in inputs.items():
        print(f'Чтение и проверка: {name}', flush=True)
        frames[name], stats[name], controls[name] = load_source(name, path, changes)
    persons, companies, payments = (frames[k] for k in ['persons', 'companies', 'payments'])
    persons['duplicate_pair'] = persons.duplicated(['SYNTHETIC_F', 'SYNTHETIC_U'], keep=False).astype('boolean')
    companies['ambiguous_company_id'] = companies.duplicated('SYNTHETIC_U', keep=False).astype('boolean')
    companies['fts_country_review'] = ((companies.FTS_FLAG.eq(1) & companies.FTS_COUNTRY_NAME.isna()) | (companies.FTS_FLAG.eq(0) & companies.FTS_COUNTRY_NAME.notna())).fillna(False).astype('boolean')
    comparable = companies.AMOUNT_WORKERS_FNS_GRADATION.notna() & companies.AMOUNT_WORKERS_SPARK_GRADATION.notna()
    companies['workers_disagree'] = companies.AMOUNT_WORKERS_FNS_GRADATION.ne(companies.AMOUNT_WORKERS_SPARK_GRADATION).where(comparable, pd.NA).astype('boolean')
    for c in ['PAY_AMT', 'PAY_CNT']:
        payments[c.lower() + '_missing'] = payments[c].isna().astype('boolean')
        payments[c.lower() + '_zero'] = payments[c].eq(0).fillna(False).astype('boolean')
    payments['repeated_pair'] = payments.duplicated(['PAYER', 'BENEFICIARY'], keep=False).astype('boolean')
    payments['self_payment'] = payments.PAYER.eq(payments.BENEFICIARY).astype('boolean')
    known = set(companies.SYNTHETIC_U)
    ambiguous = set(companies.loc[companies.ambiguous_company_id, 'SYNTHETIC_U'])
    lookup = companies.loc[~companies.ambiguous_company_id].drop(columns='source_row')
    all_ids = sorted(known | set(persons.SYNTHETIC_U) | set(payments.PAYER) | set(payments.BENEFICIARY))
    nodes = pd.DataFrame({'SYNTHETIC_U': pd.Series(all_ids, dtype='string')}).merge(lookup, on='SYNTHETIC_U', how='left', validate='one_to_one')
    nodes['profile_status'] = pd.Series(['ambiguous' if x in ambiguous else 'matched' if x in known else 'missing' for x in nodes.SYNTHETIC_U], dtype='string')
    nodes['in_profile'] = nodes.SYNTHETIC_U.isin(known).astype('boolean')
    status = nodes.set_index('SYNTHETIC_U').profile_status
    persons['company_profile_status'] = persons.SYNTHETIC_U.map(status).astype('string')
    payments['payer_profile_status'] = payments.PAYER.map(status).astype('string')
    payments['beneficiary_profile_status'] = payments.BENEFICIARY.map(status).astype('string')
    # Проверяем реальный join каждой стороны, не только map.
    for key in ['PAYER', 'BENEFICIARY']:
        joined = payments[['source_row', key, 'PAY_AMT', 'PAY_CNT']].merge(nodes[['SYNTHETIC_U', 'profile_status']], left_on=key, right_on='SYNTHETIC_U', how='left', validate='many_to_one')
        require(len(joined) == len(payments) and joined.source_row.is_unique and joined.profile_status.notna().all(), 'Соединение изменило платежные строки')
        for c in ['PAY_AMT', 'PAY_CNT']:
            require(total(joined[c]) == controls['payments'][c], f'Соединение изменило {c}')
        del joined
    prepared = {'person_links_prepared': persons, 'companies_prepared': companies, 'payments_prepared': payments, 'company_nodes': nodes}
    for name, d in frames.items():
        require(len(d) == stats[name]['rows_in'], f'{name}: потеря строк')
        for c, v in controls[name].items():
            require(total(d[c]) == v, f'{name}.{c}: изменилась контрольная сумма')
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='l03-', dir=out.parent))
    try:
        schema, manifest = {}, []
        for name, d in prepared.items():
            print(f'Экспорт и проверка: {name}', flush=True)
            schema[name] = {c: str(t) for c, t in d.dtypes.items()}
            require('object' not in schema[name].values(), f'{name}: неявный тип object')
            target = temp / f'{name}.csv.gz'
            csv_write(d, target)
            manifest.append({'file': target.name, 'rows': len(d), 'columns': len(d.columns), 'sha256': sha256(target)})
        json_write(temp / 'schema.json', schema)
        for name, d in prepared.items():
            print(f'Повторное чтение: {name}', flush=True)
            restored = read_prepared(temp, name)
            pd.testing.assert_frame_equal(d.reset_index(drop=True), restored, check_exact=True)
        for name, path in inputs.items():
            require(sha256(path) == fingerprints[name], f'Исходный файл изменился: {name}')
        csv_write(pd.DataFrame(changes), temp / 'cleaning_changes.csv')
        quality = {
            'company_status_counts': {str(k): int(v) for k, v in nodes.profile_status.value_counts().items()},
            'ambiguous_company_ids': len(ambiguous),
            'ambiguous_company_rows': int(companies.ambiguous_company_id.sum()),
            'fts_country_review_rows': int(companies.fts_country_review.sum()),
            'workers_disagree_rows': int(companies.workers_disagree.sum()),
            'workers_comparison_unknown_rows': int(companies.workers_disagree.isna().sum()),
            'duplicate_person_pairs_extra': int(persons.duplicated(['SYNTHETIC_F', 'SYNTHETIC_U']).sum()),
            'self_payment_rows': int(payments.self_payment.sum()),
            'self_payment_amount': total(payments.loc[payments.self_payment, 'PAY_AMT']),
            'repeated_pair_rows': int(payments.repeated_pair.sum()),
            'payer_missing_rows': int(payments.payer_profile_status.eq('missing').sum()),
            'beneficiary_missing_rows': int(payments.beneficiary_profile_status.eq('missing').sum()),
        }
        for c in ['PAY_AMT', 'PAY_CNT']:
            quality[c + '_missing'] = int(payments[c].isna().sum())
            quality[c + '_zero'] = int(payments[c].eq(0).sum())
        metrics = {'pipeline_version': VERSION, 'input_sha256': fingerprints, 'tables': stats, 'control_sums': controls, 'quality': quality, 'checks': {'rows_preserved': True, 'exact_numeric_sums': True, 'safe_joins': True, 'full_export_roundtrip': True, 'raw_unchanged': True}}
        json_write(temp / 'quality_metrics.json', metrics)
        json_write(temp / 'output_manifest.json', manifest)
        lines = ['# L03. Отчёт об очистке', '', 'Отчёт автоматически сформирован по текущим трём CSV. Период платежей, валюта и единицы сумм неизвестны.', '', '## Строки', '', '| Таблица | Вход | Выход | Удалено | Изменено значений/пропусков в строках |', '|---|---:|---:|---:|---:|']
        for name, s in stats.items():
            lines.append(f'| {name} | {s["rows_in"]} | {s["rows_out"]} | 0 | {s["rows_with_value_or_missing_changes"]} |')
        lines += ['', '## Правила', '', '- Исходные CSV не изменялись; SHA-256 записан в quality_metrics.json.', '- ID и ОКВЭД остаются строками, ведущие нули сохранены. Удалены только внешние пробелы.', '- Пустые поля и известные маркеры неизвестной географии заменены на NA. Остальные текстовые маркеры автоматически не угадываются.', '- Числа проверены через Decimal и приведены к nullable Int64; бинарные флаги к Int8. Дробные, отрицательные, бесконечные или неверные числа останавливают запуск без публикации результатов.', '- Неизвестные числа остаются NA. Нулевые платежные значения сохраняются с отдельными флагами.', '- Строки не удалены: даже полное совпадение платёжных строк не доказывает повтор одной операции при неизвестном периоде.', '- full_duplicate — полное совпадение исходных значений; normalized_duplicate — совпадение после нормализации. Повторы пары помечены отдельно.', '- Повторный ID компании считается неоднозначным. Исходные варианты сохранены; в company_nodes один узел без выбранных спорных атрибутов.', '- Самопереводы сохранены отдельно помеченными. Они не названы внешним оборотом.', '- workers_disagree = NA, если сравнение двух источников работников невозможно. False означает проверенное совпадение.', '- Фильтрация по ритейлу не применяется в L03. Она будет отдельным шагом и не должна исключать внешних контрагентов.', '', 'Подробные счётчики каждого преобразования: cleaning_changes.csv. source_row — номер CSV-записи с учётом заголовка; при многострочных полях это не физический номер строки.', '', '## Контрольные суммы', '', '| Таблица / поле | До | После |', '|---|---:|---:|']
        for name, fields in controls.items():
            for c, v in fields.items():
                lines.append(f'| {name}.{c} | {v} | {total(frames[name][c])} |')
        lines += ['', '## Проверки качества', '', '| Показатель | Значение |', '|---|---:|']
        for name, s in stats.items():
            lines.append(f'| {name}: полных дублей сверх первого | {s["full_duplicate_extra_rows"]} |')
        for k, v in quality.items():
            if not isinstance(v, dict):
                lines.append(f'| {k} | {v} |')
        lines += ['', '## Выполненные проверки', '', 'Сохранены все строки и точные суммы. Ключ company_nodes уникален. Соединения сторон платежа many-to-one не меняют суммы. Все значения, пропуски и типы полностью совпали после экспорта и повторного чтения. Исходники сохранили SHA-256.', '', 'Повторяемость двух независимых запусков проверяется отдельно в VALIDATION.md поставки.', '', '## Ограничения', '', 'Нет подтверждения периода, валюты и единиц платежей/выручки. Нет target или готовой обучающей выборки. География регистрации не равна всем регионам присутствия. Платёж не доказывает роль поставщика, связь физлица не доказывает владение. ФТС не доказывает текущий импорт. Неоднозначные профили и отсутствующие участники не дополнены предположениями.', '', '## Использование', '', 'Для последующих расчётов используйте company_nodes как уникальный справочник; companies_prepared сохраняет все исходные профили и не подходит для прямого many-to-one join без обработки повторных ID. CSV сжат gzip, разделитель запятая, кодировка UTF-8. Типы восстанавливает read_prepared() из prepare_data.py.']
        (temp / 'cleaning_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        if out.exists():
            out.rmdir()  # Только ранее проверенная пустая папка.
        temp.rename(out)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return metrics


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--persons', required=True, type=Path, help='CSV связей физлиц')
    p.add_argument('--companies', required=True, type=Path, help='CSV профилей компаний')
    p.add_argument('--payments', required=True, type=Path, help='CSV платежей')
    p.add_argument('--out', required=True, type=Path, help='Новая/пустая папка результата')
    a = p.parse_args()
    try:
        prepare({'persons': a.persons, 'companies': a.companies, 'payments': a.payments}, a.out)
    except (ValueError, OSError, EOFError, StopIteration, csv.Error, pd.errors.ParserError, AssertionError) as exc:
        p.exit(1, f'Ошибка подготовки: {exc}\n')
    print(f'Готово: {a.out}')


if __name__ == '__main__':
    main()
