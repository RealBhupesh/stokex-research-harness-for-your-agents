"""Adversarial checks for the supplied-evidence research contract."""
from copy import deepcopy
import unittest

from stockex.research import REQUIRED_ROLES, build_evidence_packet, synthesize_research
from tests.test_decision_packet import valid_packet


def research_fixture():
    legacy = valid_packet()
    evidence = build_evidence_packet(legacy['metadata'], legacy['mandate'], legacy['sources'], [
        {'id': 'O1', 'field': 'revenue', 'value': 100, 'source_id': 'S1',
         'available_at': '2026-09-12T18:00:00+05:30', 'quality_status': 'VERIFIED'}])
    reports = [{'id': role, 'role': role, 'reviewer_id': role + '-analyst',
                'evidence_digest': evidence['evidence_digest'], 'status': 'COMPLETE',
                'conclusion': 'Supplied fixture conclusion',
                'findings': [{'id': 'F1', 'assessment': 'SUPPORTS',
                              'rationale': 'Fixture evidence supports this test finding',
                              'source_ids': ['S1'], 'observation_ids': ['O1']}]}
               for role in REQUIRED_ROLES]
    skeptic = {'id': 'skeptic-report', 'reviewer_id': 'independent-skeptic',
               'evidence_digest': evidence['evidence_digest'], 'status': 'COMPLETE',
               'reviews': [{'report_id': role, 'finding_id': 'F1', 'verdict': 'ACCEPT',
                            'rationale': 'Fixture finding checked against supplied observation',
                            'source_ids': ['S1'], 'observation_ids': ['O1']}
                           for role in REQUIRED_ROLES]}
    return evidence, reports, skeptic


class ResearchSynthesisTests(unittest.TestCase):
    def assertBlocked(self, evidence, reports, skeptic, code):
        result = synthesize_research(evidence, reports, skeptic)
        self.assertFalse(result['approved_for_consideration'])
        self.assertEqual(result['decision']['ic_action'], 'RETURN_FOR_WORK')
        self.assertIn(code, [error['code'] for error in result['errors']], result)

    def test_complete_cited_contract_is_deterministic_and_does_not_mutate_inputs(self):
        args = research_fixture()
        before = deepcopy(args)
        first = synthesize_research(*args)
        self.assertTrue(first['approved_for_consideration'], first)
        self.assertEqual(synthesize_research(*args), first)
        self.assertEqual(args, before)
        self.assertIn('identity', first['assurance'])

    def test_builder_detaches_inputs_and_normalizes_store_aliases(self):
        legacy = valid_packet()
        source = deepcopy(legacy['sources'][0])
        source['source_id'] = source.pop('id')
        source['uri'] = source.pop('url')
        obs = {'observation_id': 'O1', 'source_id': 'S1', 'field': 'revenue', 'value': 100}
        evidence = build_evidence_packet(legacy['metadata'], legacy['mandate'], [source], [obs])
        source['publisher'] = 'changed'
        obs['value'] = 0
        legacy['metadata']['symbol'] = 'changed'
        self.assertEqual(evidence['sources'][0]['id'], 'S1')
        self.assertEqual(evidence['observations'][0]['value'], 100)
        self.assertEqual(evidence['metadata']['symbol'], 'EXAMPLE')

    def test_tampering_evidence_or_using_stale_reports_fails(self):
        evidence, reports, skeptic = research_fixture()
        evidence['observations'][0]['value'] = 101
        self.assertBlocked(evidence, reports, skeptic, 'EVIDENCE_DIGEST_MISMATCH')
        evidence, reports, skeptic = research_fixture()
        reports[0]['evidence_digest'] = 'stale'
        self.assertBlocked(evidence, reports, skeptic, 'REPORT_EVIDENCE_MISMATCH')

    def test_unknown_observation_and_source_citations_fail(self):
        for field, code in [('source_ids', 'SOURCE_CITATION_INVALID'), ('observation_ids', 'OBSERVATION_CITATION_INVALID')]:
            args = research_fixture()
            args[1][0]['findings'][0][field] = ['unknown']
            self.assertBlocked(*args, code)

    def test_missing_failed_duplicate_roles_and_reviewers_fail(self):
        args = research_fixture()
        args[1].pop()
        self.assertBlocked(*args, 'SPECIALIST_ROLE_MISSING')
        args = research_fixture()
        args[1][0]['status'] = 'FAILED'
        self.assertBlocked(*args, 'REPORT_INCOMPLETE')
        args = research_fixture()
        args[1][0]['role'] = args[1][1]['role']
        self.assertBlocked(*args, 'REPORT_ROLE_INVALID')
        args = research_fixture()
        args[1][0]['reviewer_id'] = args[1][1]['reviewer_id']
        self.assertBlocked(*args, 'REVIEWER_NOT_INDEPENDENT')

    def test_self_declared_resolution_and_gate_booleans_do_not_override_concern(self):
        args = research_fixture()
        args[1][0]['findings'][0].update(assessment='BLOCKER', resolved=True)
        args[1][0]['gates'] = {'EVIDENCE_COMPLETE': True, 'IC_CLEARED': True}
        self.assertBlocked(*args, 'FINDING_NOT_CLEARED')

    def test_skeptic_requires_independent_identity_and_complete_coverage(self):
        args = research_fixture()
        args[2]['reviewer_id'] = args[1][0]['reviewer_id']
        self.assertBlocked(*args, 'SKEPTIC_NOT_INDEPENDENT')
        args = research_fixture()
        args[2]['reviews'].pop()
        self.assertBlocked(*args, 'SKEPTICAL_COVERAGE_INCOMPLETE')
        args = research_fixture()
        args[2]['reviews'][0]['verdict'] = 'UNRESOLVED'
        self.assertBlocked(*args, 'SKEPTICAL_CHALLENGE_UNRESOLVED')

    def test_future_observations_and_sources_fail(self):
        evidence, reports, skeptic = research_fixture()
        evidence['observations'][0]['available_at'] = '2026-09-15T00:00:00Z'
        self.assertBlocked(evidence, reports, skeptic, 'OBSERVATION_UNAVAILABLE')
        evidence['sources'][0]['available_at'] = '2026-09-15T00:00:00Z'
        self.assertBlocked(evidence, reports, skeptic, 'EVIDENCE_AFTER_CUTOFF')

    def test_unresolved_controlling_evidence_blocks_even_with_resolved_flag(self):
        args = research_fixture()
        args[0]['controlling_evidence'] = [{'id': 'C1', 'source_ids': ['S1'], 'observation_ids': ['O1'], 'resolved': True}]
        self.assertBlocked(*args, 'UNRESOLVED_CONTROLLING_EVIDENCE')

    def test_malformed_untrusted_inputs_fail_closed_without_crash(self):
        for field, value in [('reports', {}), ('skeptic', None), ('evidence', None)]:
            args = list(research_fixture())
            args[{'evidence': 0, 'reports': 1, 'skeptic': 2}[field]] = value
            self.assertFalse(synthesize_research(*args)['valid'])
        for value in (None, [], {}, True, 1):
            for key in ('id', 'role', 'reviewer_id', 'findings'):
                args = research_fixture()
                args[1][0][key] = value
                self.assertFalse(synthesize_research(*args)['valid'])
            args = research_fixture()
            args[1][0]['findings'][0]['observation_ids'] = [value]
            self.assertFalse(synthesize_research(*args)['valid'])

    def test_mode_specific_controls_remain_mandatory_after_specialist_clearance(self):
        for mode, code in (("ASYMMETRIC_SPECULATION", "SPECULATION_CONTROLS_MISSING"),
                           ("AGGRESSIVE_SHORT_TERM", "TRADE_PLAN_MISSING")):
            evidence, reports, skeptic = research_fixture()
            evidence["mandate"]["mode"] = mode
            evidence = build_evidence_packet(evidence["metadata"], evidence["mandate"],
                                             evidence["sources"], evidence["observations"])
            for report in reports:
                report["evidence_digest"] = evidence["evidence_digest"]
            skeptic["evidence_digest"] = evidence["evidence_digest"]
            self.assertBlocked(evidence, reports, skeptic, code)


    def test_unverified_invalidated_and_conflicting_evidence_fails(self):
        for change, code in (({"quality_status": "PROVISIONAL"}, "OBSERVATION_QUALITY_FAILED"),
                             ({"valid_from": "2026-09-15T00:00:00Z"}, "OBSERVATION_NOT_VALID_AT_CUTOFF"),
                             ({"valid_to": "2026-09-12T20:00:00Z"}, "OBSERVATION_NOT_VALID_AT_CUTOFF")):
            args = research_fixture()
            args[0]["observations"][0].update(change)
            self.assertBlocked(*args, code)
        args = research_fixture()
        other = deepcopy(args[0]["observations"][0])
        other.update(id="O2", value=999)
        args[0]["observations"].append(other)
        self.assertBlocked(*args, "OBSERVATION_CONFLICT")



if __name__ == '__main__':
    unittest.main()
