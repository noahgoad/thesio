import pytest
from tests.integration.test_research_conclusion import setup


def test_tampered_conclusion_rejected_on_read_export_and_retry(tmp_path):
    service,client,run = setup(tmp_path)
    body = dict(version=2,decision_id='review',verdict='insufficient',note='Need evidence',evidence_ids=[])
    service.conclude(run['run_id'],body)
    with service.repository.connection:
        service.repository.connection.execute("UPDATE research_conclusions SET body=replace(body,'Need evidence','Fabricated')")
    for operation in [lambda:service.read(run['run_id']),lambda:service.export(run['run_id']),lambda:service.conclude(run['run_id'],body)]:
        with pytest.raises(ValueError,match='CONCLUSION_INTEGRITY_MISMATCH'):
            operation()
    service.close()
