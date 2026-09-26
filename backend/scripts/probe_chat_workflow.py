"""Opt-in live LLM + real query engine, using ONLY an isolated synthetic SQLite DB.

Sends project tool contracts and clearly synthetic fixture results to the configured
model. Never connects to the project's PostgreSQL or reads real RAG documents.
No credentials, private reasoning or full prompts are printed.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from dotenv import load_dotenv
from sqlalchemy import Boolean, Column, Float, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def synthetic_engine():
    engine = create_engine('sqlite://', poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS telosia")
        meta = MetaData(schema='telosia')
        jobs = Table('occupation', meta, Column('occupation_id', Integer, primary_key=True),
                     Column('occupation_title', String), Column('anzsco_code', String), Column('is_profile_occupation', Boolean))
        profiles = Table('occupation_profile', meta, Column('occupation_profile_id', Integer, primary_key=True),
                         Column('occupation_id', Integer), Column('median_weekly_earnings', Float),
                         Column('employed', Integer), Column('source_reference_id', Integer))
        moves = Table('mobility_flow', meta, Column('mobility_flow_id', Integer, primary_key=True),
                      Column('source_occupation_id', Integer), Column('destination_occupation_id', Integer),
                      Column('worker_count', Integer), Column('financial_year', String),
                      Column('is_self_transition', Boolean), Column('source_reference_id', Integer))
        meta.create_all(connection)
        connection.execute(jobs.insert(), [{'occupation_id': i, 'occupation_title': name + ' (synthetic test)',
                                           'anzsco_code': str(9000+i), 'is_profile_occupation': True}
                                          for i, name in [(1, 'Retail Sales Assistants'), (2, 'Office Clerks'), (3, 'Teachers')]])
        connection.execute(profiles.insert(), [{'occupation_id': i, 'median_weekly_earnings': pay, 'employed': 100,
                                               'source_reference_id': 1} for i, pay in [(1, 1000), (2, 1200), (3, 1600)]])
        connection.execute(moves.insert(), [{'source_occupation_id': 1, 'destination_occupation_id': dest,
                                            'worker_count': count, 'financial_year': '2024-25',
                                            'is_self_transition': False, 'source_reference_id': 1}
                                           for dest, count in [(2, 17), (3, 12)]])
    return engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--question', default='What jobs do people move into from retail?')
    parser.add_argument('--protocol', choices=['auto', 'native', 'json'], default='auto')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env', override=True)
    # Only this child process is changed; the real .env is untouched.
    os.environ['DATABASE_URL'] = 'sqlite://'
    os.environ['CHAT_TOOL_PROTOCOL'] = args.protocol
    os.environ['CHAT_MAX_TRANSIENT_RETRIES'] = '0'
    from app.services import nvidia_chat, chat_context, chat_tools
    context, events = {}, []
    engine = synthetic_engine()
    report = {'model': os.getenv('NVIDIA_CHAT_MODEL'), 'protocol': args.protocol, 'synthetic_database': True}
    arithmetic = []
    original_execute = chat_tools.ChatToolRuntime.execute
    def traced_execute(runtime, name, arguments):
        result = original_execute(runtime, name, arguments)
        for calculation in result.get('calculations', []) + ([result] if name == 'calculate' else []):
            arithmetic.append({key: calculation.get(key) for key in ('operation', 'result', 'unit', 'error')})
        return result
    source = [{'source_id': 1, 'publisher': 'Synthetic test fixture', 'dataset_title': 'Invented data; not real occupations or statistics'}]
    test_prompt = nvidia_chat.SYSTEM_PROMPT + '\nTEST ENVIRONMENT: all database rows are invented fixtures; label the answer synthetic, not real occupational evidence.'
    try:
        with Session(engine) as db, patch.object(nvidia_chat, 'SYSTEM_PROMPT', test_prompt), \
             patch.object(chat_tools.ChatToolRuntime, 'execute', traced_execute), \
             patch.object(chat_context, 'load_supporting_sources', return_value=source), \
             patch.object(chat_tools.ChatToolRuntime, '_knowledge', return_value={'available': False, 'documents': [], 'note': 'Real RAG documents excluded from this synthetic test.'}):
            answer = nvidia_chat.generate_chat_answer(args.question, context, db=db,
                     on_event=lambda event, data: events.append((event, data)) if event != 'delta' else None)
            report.update(status='partial' if context.get('budget_limited') else 'answered', answer=answer)
    except nvidia_chat.ChatModelUnavailableError as exc:
        report.update(status='error', error_code=exc.code)
    finally:
        engine.dispose()
    report.update(elapsed_ms=context.get('elapsed_ms'), tools=context.get('database_tool_names'),
                  queries=context.get('data_queries'), timings=context.get('timings'),
                  evidence_events=sum(event == 'data_result' for event, _ in events), arithmetic=arithmetic)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
