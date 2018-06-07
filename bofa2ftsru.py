#!/usr/bin/python
# -*- coding: utf-8 -*-

import csv
import datetime
import glob
import re
import sys
from decimal import Decimal
from functools import reduce


def remove_prefix(s, prefix):
    assert isinstance(s, str) and isinstance(prefix, str)
    assert s.startswith(prefix)
    return s[len(prefix):]


def parser_date(s):
    fmt = '%m/%d/%Y'
    assert re.match('^(\d{2})/(\d{2})/(\d{4})$', s)
    d = datetime.datetime.strptime(s, fmt).date()
    assert d.strftime(fmt) == s
    return d


def parser_prefixed_date(prefix):
    def f(s):
        return parser_date(remove_prefix(s, prefix))

    return f


def parser_money(s):
    assert re.match('^-?(0|[1-9][0-9]*)\.\d{2}$', s)
    r = Decimal(s.strip('"'))
    return r


def parser_equal(v):
    def f(s):
        assert s == v
        return s

    return f


def parser_text(s):
    return s


def parse(values, parsers):
    assert len(values) == len(parsers)
    return [e[0](e[1]) for e in zip(parsers, values)]


def total_credits(data):
    return sum([e['amount'] for e in data['records'] if e['amount'] >= 0])


def total_debits(data):
    return sum([e['amount'] for e in data['records'] if e['amount'] < 0])


def validate(data):
    assert data['beginning_date'] < data['ending_date']

    r = data['records']
    assert len(r) > 0
    assert data['total_credits'] == total_credits(data)
    assert data['total_debits'] == total_debits(data)
    assert not [e for e in r if e['date'] < data['beginning_date'] or e['date'] > data['ending_date']]
    assert not [e for e in r if e['balance_before'] + e['amount'] != e['running_balance']]

    def check(a, b):
        assert a['date'] <= b['date']
        assert a['running_balance'] == b['balance_before']
        return b

    assert r[0]['balance_before'] == data['beginning_balance']
    reduce(check, r)
    assert r[-1]['running_balance'] == data['ending_balance']

    assert data['beginning_balance'] + data['total_credits'] + data['total_debits'] == data['ending_balance']


def parse_file(file_name):
    with open(file_name) as f:
        content = f.readlines()
    content = list(csv.reader(content))

    parse(content.pop(0), [parser_equal('Description'), parser_equal(''), parser_equal('Summary Amt.')])

    beginning_date, _, beginning_balance \
        = parse(content.pop(0), [parser_prefixed_date('Beginning balance as of '), parser_equal(''), parser_money])
    _, _, total_credits = parse(content.pop(0), [parser_equal('Total credits'), parser_equal(''), parser_money])
    _, _, total_debits = parse(content.pop(0), [parser_equal('Total debits'), parser_equal(''), parser_money])
    ending_date, _, ending_balance \
        = parse(content.pop(0), [parser_prefixed_date('Ending balance as of '), parser_equal(''), parser_money])

    parse(content.pop(0), [])
    parse(content.pop(0), [parser_equal('Date'), parser_equal('Description'), parser_equal('Amount'),
                           parser_equal('Running Bal.')])

    beginning_date_0, beginning_date_1, _, beginning_balance_0 \
        = parse(content.pop(0), [parser_date, parser_prefixed_date('Beginning balance as of '),
                                 parser_equal(''), parser_money])

    assert beginning_date == beginning_date_0 and beginning_date == beginning_date_1
    assert beginning_balance == beginning_balance_0

    result = {
        'file_name': file_name,
        'beginning_date': beginning_date,
        'beginning_balance': beginning_balance,
        'total_credits': total_credits,
        'total_debits': total_debits,
        'ending_date': ending_date,
        'ending_balance': ending_balance,
        'records': []
    }

    for s in content:
        record_date, description, amount, running_balance \
            = parse(s, [parser_date, parser_text, parser_money, parser_money])
        result['records'].append({
            'date': record_date,
            'description': description,
            'balance_before': running_balance - amount,
            'amount': amount,
            'running_balance': running_balance
        })

    validate(result)

    with open(file_name) as f:
        assert f.read() == data_to_str(result)

    return result


def to_date(d):
    return d.strftime('%m/%d/%Y')


def data_to_str(data):
    s = f"""Description,,Summary Amt.
Beginning balance as of {to_date(data["beginning_date"])},,"{data["beginning_balance"]}"
Total credits,,"{data["total_credits"]}"
Total debits,,"{data["total_debits"]}"
Ending balance as of {to_date(data["ending_date"])},,"{data["ending_balance"]}"

Date,Description,Amount,Running Bal.
{to_date(data["beginning_date"])},Beginning balance as of {to_date(data["beginning_date"])},,"{data["beginning_balance"]}"
"""
    for r in data["records"]:
        s += f'{to_date(r["date"])},"{r["description"]}","{r["amount"]}","{r["running_balance"]}"\n'
    return s


def normalize_data(d):
    d['beginning_balance'] = d['records'][0]['balance_before']
    d['ending_balance'] = d['records'][-1]['running_balance']
    d['total_credits'] = total_credits(d)
    d['total_debits'] = total_debits(d)


def merge_data(a, b):
    shared_a = list(filter(lambda e: e['date'] >= b['beginning_date'], a['records']))
    if shared_a:
        shared_b = b['records'][0:len(shared_a)]
        assert shared_a == shared_b
    records = list(filter(lambda e: e['date'] < b['beginning_date'], a['records']))
    records.extend(b['records'])
    a['records'] = records
    a['ending_date'] = b['ending_date']
    normalize_data(a)
    return a


def sort_data_list(data_list):
    assert len(set([d['beginning_date'] for d in data_list])) == len(data_list)
    result = sorted(data_list, key=lambda v: v['beginning_date'])
    return result


def validate_data_list(data_list):
    def test(a, b):
        assert a['beginning_date'] < b['beginning_date']
        assert a['ending_date'] < b['ending_date']
        return b

    reduce(test, data_list)


def save(data, file_name):
    with open(file_name, 'w') as f:
        f.write(data_to_str(data))


def filter_year(data, year):
    records = list(filter(lambda e: e['date'].year == year, data['records']))
    result = {
        'beginning_date': datetime.date(year, 1, 1),
        'ending_date': datetime.date(year, 12, 31),
        'records': records
    }
    normalize_data(result)
    return result


def convert(input_dir, output_file):
    file_list = glob.glob(input_dir + '/*.csv')
    data_list = list(map(parse_file, file_list))
    data_list = sort_data_list(data_list)
    validate_data_list(data_list)
    data = reduce(merge_data, data_list)
    validate(data)
    years = sorted(list(set([d['date'].year for d in data['records']])))
    for year in years:
        d = filter_year(data, year)
        validate(d)
        save(d, output_file + '/' + str(year) + '.txt')


if __name__ == '__main__':
    convert(sys.argv[1], sys.argv[2])
