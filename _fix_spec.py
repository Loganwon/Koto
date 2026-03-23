import io
import re

with open('koto.spec', 'r', encoding='utf-8') as f:
    spec_content = f.read()

# Replace the web modules block
web_modules = """    # ── web/ 全部模块 ──
    'web', 'web.app', 'web.audio_overview', 'web.audit_logger',
    'web.auth', 'web.auth_manager', 'web.auto_catalog_scheduler',
    'web.auto_execution', 'web.batch_file_ops', 'web.batch_processor',
    'web.behavior_monitor', 'web.browser_automation', 'web.calendar_manager',
    'web.clipboard_manager', 'web.clipboard_ocr_assistant', 'web.code_generator',
    'web.concept_extractor', 'web.consistency_checker', 'web.context_awareness',
    'web.context_injector', 'web.data_pipeline', 'web.doc_converter',
    'web.doc_planner', 'web.document_annotator', 'web.document_batch_annotator_v2',
    'web.document_comparator', 'web.document_direct_edit', 'web.document_editor',
    'web.document_feedback', 'web.document_generator', 'web.document_reader',
    'web.document_validator', 'web.document_workflow_executor',
    'web.docx_translator_module', 'web.email_manager', 'web.enhanced_memory_manager',
    'web.feedback_loop', 'web.file_analyzer', 'web.file_converter',
    'web.file_editor', 'web.file_fields_extractor', 'web.file_indexer',
    'web.file_organizer', 'web.file_parser', 'web.file_processor',
    'web.file_qa', 'web.file_quality_checker', 'web.file_scanner',
    'web.file_watcher', 'web.folder_catalog_organizer', 'web.image_generator',
    'web.image_manager', 'web.insight_reporter', 'web.intelligent_document_analyzer',
    'web.knowledge_base', 'web.knowledge_graph', 'web.local_executor',
    'web.local_stt', 'web.memory_api_routes', 'web.memory_integration',
    'web.memory_manager', 'web.model_manager', 'web.note_manager',
    'web.notification_manager', 'web.operation_history', 'web.organize_cleanup',
    'web.parallel_api', 'web.parallel_executor', 'web.ppt_api_routes',
    'web.ppt_generator', 'web.ppt_master', 'web.ppt_pipeline',
    'web.ppt_quality', 'web.ppt_session_manager', 'web.ppt_synthesizer',
    'web.ppt_themes', 'web.proactive_dialogue', 'web.proactive_trigger',
    'web.processed_file_network', 'web.prompt_adapter', 'web.quality_evaluator',
    'web.reminder_manager', 'web.search_engine', 'web.settings',
    'web.shared', 'web.smart_feedback', 'web.speech_transcriber',
    'web.suggestion_annotator', 'web.suggestion_engine', 'web.system_info',
    'web.task_dispatcher', 'web.task_scheduler', 'web.telegram_bot',
    'web.template_library', 'web.token_tracker', 'web.track_changes_editor',
    'web.voice_api_enhanced', 'web.voice_engine', 'web.voice_fast',
    'web.voice_input', 'web.voice_interaction', 'web.voice_recognition_enhanced',
    'web.web_searcher', 'web.windows_notifier', 'web.work_file_library',
    'web.workflow_manager',
]"""

old_web_modules_start = spec_content.find("# ── web/ 全部模块 ──")
old_web_modules_end = spec_content.find("]", old_web_modules_start) + 1

new_spec = spec_content[:old_web_modules_start] + web_modules + spec_content[old_web_modules_end:]

with open('koto.spec', 'w', encoding='utf-8') as f:
    f.write(new_spec)
