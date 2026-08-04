"""
Input guardrails for text-to-sql agent
will exeucte of the isntruction text before sending it to the agent
should check of prompt for security prospective and if there are any constraints at hand
"""

import spider_agent_workbench.paths

from spider_agent_workbench.constants import QUESTION_MAX_LENGTH
from spider_agent_workbench.schema import list_databases
from spider_agent_workbench.guardrails.guardrail_result import GuardrailResult

OFF_TOPIC_SIGNALS = (
    "translate",
    "ignore your instruction",
    "ignore above instruction",
    "ignore previous",
    "system prompt",
)


def check_db_exist(db_id:str, db_dir:str) -> GuardrailResult:
    """Check if the db actually exist or not
    if the db does not exist, say error and there is no need to reach to the prompt
    """
    present_db_list = list_databases(db_dir)
    if db_id not in present_db_list:
        return GuardrailResult(
            ok=False,
            reason="Database not present"
        )
    return GuardrailResult(ok=True)


def check_question_max_length(question:str) -> GuardrailResult:
    """Check the prompt against maximum length constraint"""
    if len(question) > QUESTION_MAX_LENGTH:
        return GuardrailResult(
            ok = False,
            reason = 'Prompt length more than the maximum permissible length'
        )
    return GuardrailResult(ok=True)

def check_for_prompt_injection(question:str) -> GuardrailResult:
    """Check if the prompt contains any instructions 
    or prompt snippets that can cause security issues
    """ 
    question_lower = question.lower()
    found = any(signal for signal in OFF_TOPIC_SIGNALS if signal in question_lower)
    if found:
        return GuardrailResult(ok=False, reason='Off signal instructions found in Prompt, cannot proceed')
    return GuardrailResult(ok=True)


def run_input_guardrails(db_id:str, db_dir:str, question:str) -> GuardrailResult:
    """Run prompt details against the input guardrails designed"""
    for check in (check_question_max_length, check_for_prompt_injection):
        result = check(question)
        if not result.ok:
            return result

    return check_db_exist(db_id, db_dir)

