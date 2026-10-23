import copy
from datetime import datetime, timezone
from unittest.mock import patch

import common
import manage_state
import notifications
from test_monitor import Base, daily_scan


class CandidateLabelTests(Base):
    def setUp(self):
        super().setUp()
        after_close = datetime(2026, 10, 15, 20, 20, tzinfo=timezone.utc)
        for module in (common, notifications, manage_state):
            self.stack.enter_context(patch.object(module, 'now_utc', return_value=after_close))

    def run_daily(self):
        common.save_json('signals.json', daily_scan())
        self.assertEqual(manage_state.main(), 0)

    def test_unconfirmed_previous_candidate_is_revalidated_not_a_new_purchase(self):
        state = common.load_json('signal_state.json')
        state['positions']['AAPL'] = {'symbol':'AAPL', 'status':'pending_entry',
            'signal_date':'2026-10-14', 'stop_usd':95, 'recommended_position_cad':20}
        common.save_json('signal_state.json', state)
        self.run_daily()
        events = common.load_json('signal_events.json')['events']
        event = next(event for event in events if event['id']=='ENTRY-AAPL-2026-10-15')
        self.assertEqual(event['type'], 'ENTRY')
        self.assertEqual(event['candidate_kind'], 'revalidated')
        self.assertEqual(event['previous_signal_date'], '2026-10-14')
        self.assertIn('CANDIDATO REVALIDADO', notifications.message(event))
        self.assertIn('não comprada', notifications.message(event))
        self.assertEqual(set(common.load_json('portfolio_state.json')['holdings']), {'COST'})

    def test_new_candidate_keeps_id_strategy_size_and_stop(self):
        before = copy.deepcopy(common.load_json('portfolio_state.json'))
        self.run_daily()
        event = next(event for event in common.load_json('signal_events.json')['events']
                     if event['id']=='ENTRY-AAPL-2026-10-15')
        self.assertEqual(event['candidate_kind'], 'new')
        self.assertIsNone(event['previous_signal_date'])
        self.assertEqual(event['stop_usd'], 975)
        self.assertEqual(event['recommended_position_cad'], 33.33)
        self.assertIn('CANDIDATO NOVO', notifications.message(event))
        self.assertEqual(common.load_json('portfolio_state.json'), before)

    def test_same_day_rerun_does_not_send_another_alert(self):
        self.run_daily()
        count = self.post.call_count
        self.run_daily()
        self.assertEqual(self.post.call_count, count)

    def test_legacy_events_are_not_invented_as_new_candidates(self):
        event = {'type':'ENTRY', 'symbol':'WMT', 'signal_date':'2026-10-15',
                 'recommended_position_cad':33.33, 'stop_usd':100, 'id':'legacy'}
        text = notifications.message(event)
        self.assertIn('HISTÓRICO SEM CLASSIFICAÇÃO', text)
        self.assertNotIn('CANDIDATO NOVO', text)
