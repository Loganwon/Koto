"""Browser guards for shared body-level UI primitives."""

import pytest


def _open_unsaved_dialog(page) -> None:
    page.evaluate(
        """
        () => {
          const name = 'ui-token-check.pptx';
          window.state.openTabs = [{
            path: name,
            name,
            ext: 'pptx',
            fileType: 'pptx',
            fileId: 'ui-token-check',
            serverData: { value: 1 },
            savedSnapshot: JSON.stringify({ value: 1 }),
            modified: true,
          }];
          window.state.activeTabPath = name;
          window.state.fileType = 'pptx';
          window.state.fileId = 'ui-token-check';
          window.state.activeEditor = { serialize: () => ({ value: 2 }) };
          window.WA.showCloseWarning([{ path: name, name }]);
        }
        """
    )
    page.locator("#wa-close-warn-dialog").wait_for(state="visible")


@pytest.mark.e2e
def test_body_level_dialogs_follow_shared_light_and_dark_tokens(
    e2e_page, e2e_base_url, console_errors
):
    page = e2e_page
    page.goto(f"{e2e_base_url}/", wait_until="domcontentloaded")
    page.wait_for_function(
        "window.WA && window.KotoDialog && window.state",
        timeout=60_000,
    )
    page.wait_for_timeout(1_500)

    expected = {
        "light": {
            "surface": "rgb(255, 255, 255)",
            "text": "rgb(13, 22, 38)",
            "accent": "rgb(37, 99, 235)",
        },
        "dark": {
            "surface": "rgb(22, 28, 40)",
            "text": "rgb(237, 242, 252)",
            "accent": "rgb(91, 157, 245)",
        },
    }

    for theme, colors in expected.items():
        page.evaluate(
            "theme => document.documentElement.setAttribute('data-theme', theme)",
            theme,
        )
        page.evaluate(
            """
            () => {
              document.getElementById('legacyButtonAliasCheck')?.remove();
              const button = document.createElement('button');
              button.id = 'legacyButtonAliasCheck';
              button.className = 'btn-primary btn-sm';
              button.textContent = 'Legacy alias';
              document.body.appendChild(button);
            }
            """
        )
        legacy_button = page.locator("#legacyButtonAliasCheck")
        assert legacy_button.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        ) == colors["accent"]
        assert legacy_button.evaluate("el => getComputedStyle(el).minHeight") == "32px"
        legacy_button.evaluate("el => el.remove()")

        page.evaluate(
            """
            window.KotoDialog({
              title: 'UI token check',
              message: 'Shared dialog primitives',
              confirmText: 'OK',
              cancelText: 'Cancel',
            })
            """
        )
        page.locator(".koto-dialog-visible .koto-dialog").wait_for(state="visible")
        koto_dialog = page.locator(".koto-dialog")
        koto_confirm = page.locator(".koto-dialog-confirm")
        assert koto_dialog.evaluate("el => getComputedStyle(el).backgroundColor") == colors[
            "surface"
        ]
        assert koto_dialog.evaluate("el => getComputedStyle(el).color") == colors["text"]
        assert koto_confirm.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        ) == colors["accent"]
        page.locator(".koto-dialog-cancel").click()
        page.wait_for_timeout(300)

        page.evaluate("window.WA.openFolderAsWorkspace()")
        folder_overlay = page.locator("#wa-open-folder-overlay")
        folder_overlay.wait_for(state="visible")
        folder_dialog = folder_overlay.locator(".wa-dlg-box")
        folder_primary = folder_overlay.locator(".wa-btn.primary")
        assert folder_dialog.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        ) == colors["surface"]
        assert folder_dialog.evaluate("el => getComputedStyle(el).color") == colors["text"]
        assert folder_primary.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        ) == colors["accent"]
        page.evaluate("window.WA.closeFolderOverlay()")

        _open_unsaved_dialog(page)
        close_overlay = page.locator("#wa-close-warn-overlay")
        close_dialog = page.locator("#wa-close-warn-dialog")
        close_primary = close_overlay.locator(".wa-close-warn-save")
        assert close_overlay.evaluate("el => el.parentElement.tagName") == "BODY"
        assert close_dialog.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        ) == colors["surface"]
        assert close_dialog.evaluate("el => getComputedStyle(el).color") == colors["text"]
        assert close_primary.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        ) == colors["accent"]
        page.evaluate("window.WA._closeWarnCancel()")

        page.evaluate(
            """
            () => {
              window.__agentConfirmResult = null;
              window.showAgentConfirmDialog(
                'write_file',
                { path: 'workspace/report.docx' },
                '即将写入工作区文件。'
              ).then(result => { window.__agentConfirmResult = result; });
            }
            """
        )
        agent_overlay = page.locator(".agent-dialog-overlay")
        agent_dialog = page.locator(".agent-confirm-dialog")
        agent_overlay.wait_for(state="visible")
        agent_primary = agent_dialog.locator(".ui-dialog-button.primary")
        assert agent_dialog.get_attribute("role") == "dialog"
        assert agent_dialog.get_attribute("aria-modal") == "true"
        assert agent_dialog.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        ) == colors["surface"]
        assert agent_dialog.evaluate("el => getComputedStyle(el).color") == colors[
            "text"
        ]
        assert agent_primary.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        ) == colors["accent"]
        agent_dialog.locator('[data-agent-action="cancel"]').click()
        page.wait_for_function(
            "window.__agentConfirmResult && window.__agentConfirmResult.confirmed === false"
        )

        page.evaluate(
            """
            () => {
              window.__agentChoiceResult = null;
              window.showAgentChoiceDialog(
                '选择处理方式',
                [
                  { label: '创建副本', value: 'copy' },
                  { label: '覆盖原文件', value: 'overwrite' },
                ]
              ).then(result => { window.__agentChoiceResult = result; });
            }
            """
        )
        choice_dialog = page.locator(".agent-choice-dialog")
        choice_dialog.wait_for(state="visible")
        assert choice_dialog.get_attribute("role") == "dialog"
        assert choice_dialog.locator(".agent-choice-option").count() == 2
        choice_dialog.locator(".agent-choice-option").first.click()
        page.wait_for_function(
            "window.__agentChoiceResult && window.__agentChoiceResult.selected === 'copy'"
        )

        template_modal = page.locator("#newSessionModal")
        template_modal.evaluate("el => el.classList.add('active')")
        template_modal.wait_for(state="visible")
        template_surface = template_modal.locator(".modal")
        assert template_surface.evaluate(
            "el => getComputedStyle(el).backgroundColor"
        ) == colors["surface"]
        assert template_surface.evaluate("el => getComputedStyle(el).color") == colors[
            "text"
        ]
        assert template_modal.evaluate(
            "el => getComputedStyle(el).zIndex"
        ) == "5000"
        template_modal.evaluate("el => el.classList.remove('active')")

        page.evaluate("window.toggleHotkeySheet()")
        hotkey_overlay = page.locator("#hotkeySheetModal")
        hotkey_overlay.wait_for(state="visible")
        hotkey_dialog = hotkey_overlay.locator(".modal")
        assert hotkey_overlay.get_attribute("aria-hidden") == "false"
        assert hotkey_dialog.get_attribute("role") == "dialog"
        assert hotkey_dialog.evaluate("el => getComputedStyle(el).width") == "460px"
        assert hotkey_dialog.locator(".ui-dialog-button.secondary").count() == 1
        page.evaluate("window.closeHotkeySheet()")
        assert hotkey_overlay.get_attribute("aria-hidden") == "true"

        page.evaluate(
            """
            () => {
              localStorage.setItem('koto.projectOptions', JSON.stringify([
                { key: 'default', label: '默认项目' },
                { key: 'work', label: '工作' },
              ]));
              window.openProjectsManager();
            }
            """
        )
        projects_overlay = page.locator("#projectsManagerModal")
        projects_overlay.wait_for(state="visible")
        projects_dialog = projects_overlay.locator(".modal")
        project_rows = projects_overlay.locator(".proj-mgr-item")
        assert projects_overlay.get_attribute("aria-hidden") == "false"
        assert projects_dialog.get_attribute("role") == "dialog"
        assert projects_dialog.evaluate("el => getComputedStyle(el).width") == "340px"
        assert project_rows.count() == 2
        assert project_rows.first.locator(".proj-mgr-default").inner_text() == "默认"

        project_name = projects_overlay.locator("#newProjectNameInput")
        project_name.fill("UI 回归")
        projects_overlay.locator(".proj-mgr-add .ui-dialog-button.primary").click()
        assert project_rows.count() == 3
        assert page.evaluate(
            """
            () => JSON.parse(localStorage.getItem('koto.projectOptions') || '[]')
              .some(project => project.label === 'UI 回归')
            """
        )
        page.evaluate("window.closeProjectsManager()")
        assert projects_overlay.get_attribute("aria-hidden") == "true"

    assert console_errors == []


@pytest.mark.e2e
def test_ghost_button_surfaces_share_one_primitive(
    e2e_page, e2e_base_url, console_errors
):
    page = e2e_page
    page.route(
        "**/api/batch/jobs",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body="""{
              "success": true,
              "jobs": [{
                "job_id": "ui-ghost-check",
                "name": "UI ghost check",
                "status": "running",
                "total_items": 4,
                "processed_items": 2,
                "output_dir": "C:/Koto/output"
              }]
            }""",
        ),
    )
    page.goto(f"{e2e_base_url}/", wait_until="domcontentloaded")
    page.wait_for_function(
        "window.openBatchJobsPanel && window.refreshBatchJobs",
        timeout=60_000,
    )
    print("token-modal: globals ready")
    page.wait_for_timeout(1_000)

    top_button = page.locator(".top-actions .ui-ghost-button--glass")
    assert top_button.count() == 1
    assert top_button.get_attribute("style") is None
    assert top_button.evaluate("el => getComputedStyle(el).display") in {
        "flex",
        "inline-flex",
    }
    assert top_button.evaluate("el => getComputedStyle(el).minHeight") == "32px"
    assert top_button.locator("svg").evaluate(
        "el => getComputedStyle(el).marginRight"
    ) == "0px"

    artifact_buttons = page.locator(
        ".artifacts-actions .ui-ghost-button--icon"
    )
    assert artifact_buttons.count() == 2
    artifact_width = artifact_buttons.first.evaluate(
        "el => parseFloat(getComputedStyle(el).width)"
    )
    assert artifact_width == pytest.approx(32, abs=0.1)

    page.evaluate(
        """
        () => {
          document.getElementById('ghostAliasCheck')?.remove();
          const button = document.createElement('button');
          button.id = 'ghostAliasCheck';
          button.className = 'ghost-btn';
          button.textContent = 'Legacy ghost alias';
          document.body.appendChild(button);
        }
        """
    )
    legacy_alias = page.locator("#ghostAliasCheck")
    assert legacy_alias.evaluate("el => getComputedStyle(el).display") == "inline-flex"
    assert legacy_alias.evaluate("el => getComputedStyle(el).minHeight") == "32px"
    legacy_alias.evaluate("el => el.remove()")

    page.evaluate(
        """
        () => {
          document.getElementById('closeAliasCheck')?.remove();
          const button = document.createElement('button');
          button.id = 'closeAliasCheck';
          button.className = 'close-panel';
          button.setAttribute('aria-label', 'Legacy close alias');
          button.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';
          document.body.appendChild(button);
        }
        """
    )
    legacy_close = page.locator("#closeAliasCheck")
    assert legacy_close.evaluate(
        "el => parseFloat(getComputedStyle(el).width)"
    ) == pytest.approx(36, abs=0.1)
    assert legacy_close.locator("svg").evaluate(
        "el => parseFloat(getComputedStyle(el).width)"
    ) == pytest.approx(16, abs=0.1)
    legacy_close.evaluate("el => el.remove()")

    page.evaluate("window.openBatchJobsPanel()")
    batch_panel = page.locator("#batchPanelModal")
    batch_panel.wait_for(state="visible")
    batch_dialog = batch_panel.locator(".batch-panel")
    batch_close = batch_panel.locator(".ui-close-button--quiet")
    assert batch_panel.get_attribute("aria-hidden") == "false"
    assert batch_panel.evaluate("el => el.classList.contains('active')")
    assert batch_dialog.get_attribute("role") == "dialog"
    assert batch_dialog.get_attribute("aria-modal") == "true"
    assert batch_close.get_attribute("aria-label") == "关闭批量任务"
    assert batch_close.evaluate("el => document.activeElement === el")
    assert batch_close.evaluate(
        "el => getComputedStyle(el).borderTopColor"
    ) == "rgba(0, 0, 0, 0)"
    compact_button = batch_panel.locator(
        ".batch-job-output .ui-ghost-button--compact"
    )
    compact_button.wait_for(state="visible")
    assert compact_button.get_attribute("style") is None
    assert compact_button.evaluate("el => getComputedStyle(el).minHeight") == "26px"
    assert compact_button.evaluate("el => getComputedStyle(el).paddingTop") == "2px"
    assert compact_button.evaluate("el => getComputedStyle(el).paddingLeft") == "8px"
    page.evaluate("window.closeBatchJobsPanel()")
    assert batch_panel.get_attribute("aria-hidden") == "true"
    assert not batch_panel.evaluate("el => el.classList.contains('active')")

    assert console_errors == []


@pytest.mark.e2e
def test_suggestion_panel_states_and_compact_close_buttons(
    e2e_page, e2e_base_url, console_errors
):
    page = e2e_page
    calls = {"count": 0}

    def fulfill_suggestions(route):
        calls["count"] += 1
        if calls["count"] == 1:
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=(
                    'event: progress\ndata: {"message":"正在检查","progress":50}\n\n'
                    'event: suggestion\ndata: {"suggestion":{"id":"s1","title":"措辞",'
                    '"original_text":"旧句","suggested_text":"新句","reason":"更清晰"}}\n\n'
                ),
            )
        elif calls["count"] == 2:
            route.fulfill(status=200, content_type="text/event-stream", body="")
        else:
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"error":"analysis failed"}',
            )

    page.route("**/api/document/suggest-stream", fulfill_suggestions)
    page.goto(f"{e2e_base_url}/", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => typeof window.KotoDialog === 'function'",
        timeout=60_000,
    )
    assert page.evaluate(
        """
        () => ({
          open: typeof window.openSuggestionPanel,
          close: typeof window.closeSuggestionPanel,
        })
        """
    ) == {"open": "function", "close": "function"}
    page.wait_for_timeout(1_000)

    api_banner = page.locator("#apiKeyBanner")
    api_close = api_banner.locator(".ui-close-button--inverse")
    page.evaluate(
        """
        () => {
          if (typeof window.switchToChatView === 'function') window.switchToChatView();
          const banner = document.getElementById('apiKeyBanner');
          banner.hidden = false;
          banner.setAttribute('aria-hidden', 'false');
        }
        """
    )
    assert api_close.get_attribute("aria-label") == "关闭 API Key 提醒"
    assert api_close.evaluate(
        "el => parseFloat(getComputedStyle(el).width)"
    ) == pytest.approx(28, abs=0.1)
    api_close.evaluate("el => el.click()")
    assert api_banner.get_attribute("aria-hidden") == "true"
    assert api_banner.evaluate("el => el.hidden")

    assert page.locator("#tokenMonitor").count() == 0

    page.evaluate("window.openSuggestionPanel('sample.docx', '优化措辞')")
    overlay = page.locator("#suggestionPanelModal")
    dialog = overlay.locator(".suggestion-panel")
    overlay.wait_for(state="visible")
    page.wait_for_function(
        "document.getElementById('suggestionProgressText').textContent === '分析完成'"
    )
    assert overlay.get_attribute("aria-hidden") == "false"
    assert dialog.get_attribute("role") == "dialog"
    assert dialog.get_attribute("aria-modal") == "true"
    assert overlay.locator(".ui-close-button").evaluate(
        "el => document.activeElement === el"
    )
    assert overlay.locator("#suggestionStats").is_visible()
    assert overlay.locator("#suggestionFooter").is_visible()
    assert overlay.locator("#totalSuggestions").inner_text() == "1"
    assert overlay.locator("#acceptedCount").inner_text() == "1"
    assert overlay.locator("#rejectedCount").inner_text() == "0"

    overlay.locator(".btn-reject").click()
    assert overlay.locator("#acceptedCount").inner_text() == "0"
    assert overlay.locator("#rejectedCount").inner_text() == "1"
    page.evaluate("window.closeSuggestionPanel()")
    assert overlay.get_attribute("aria-hidden") == "true"
    assert not overlay.evaluate("el => el.classList.contains('active')")

    page.evaluate("window.openSuggestionPanel('empty.docx', '检查')")
    overlay.wait_for(state="visible")
    page.wait_for_function(
        "document.getElementById('suggestionProgressText').textContent === '暂无修改建议'"
    )
    assert overlay.locator("#suggestionStats").is_hidden()
    assert overlay.locator("#suggestionFooter").is_hidden()
    page.evaluate("window.closeSuggestionPanel()")

    page.evaluate("window.openSuggestionPanel('broken.docx', '检查')")
    overlay.wait_for(state="visible")
    page.wait_for_function(
        "document.getElementById('suggestionProgressText').textContent === '分析失败'"
    )
    assert "分析失败" in overlay.locator("#suggestionList").inner_text()
    assert overlay.locator("#suggestionStats").is_hidden()
    assert overlay.locator("#suggestionFooter").is_hidden()
    page.evaluate("window.closeSuggestionPanel()")

    assert console_errors == []


@pytest.mark.e2e
def test_skill_creation_modals_share_current_state(
    e2e_page, e2e_base_url, console_errors
):
    page = e2e_page
    page.route(
        "**/api/skills",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"skills":[{"id":"ui-check","icon":"🧪","name":"UI check"}]}',
        ),
    )
    page.route(
        "**/api/skillmarket/templates/ui-check",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"has_template":false}',
        ),
    )
    page.goto(f"{e2e_base_url}/", wait_until="domcontentloaded")
    page.wait_for_function(
        """
        () => window.openCreateBindingModal
          && window.openCreateSkillModal
          && window.openCatalogWizard
          && window.openSkillEditor
          && window.spOpenTemplateUpload
          && window.KotoModalState
        """,
        timeout=60_000,
    )
    page.wait_for_timeout(1_000)
    assert page.locator("#tokenMonitor").count() == 0

    def install_opener(opener_id: str) -> None:
        page.evaluate(
            """
            openerId => {
              document.getElementById(openerId)?.remove();
              const opener = document.createElement('button');
              opener.id = openerId;
              opener.type = 'button';
              opener.textContent = openerId;
              document.body.appendChild(opener);
              opener.focus();
            }
            """,
            opener_id,
        )

    install_opener("skillModalOpener")
    page.evaluate("window.openCreateSkillModal()")
    skill_modal = page.locator("#createSkillModal")
    skill_modal.wait_for(state="visible")
    assert skill_modal.get_attribute("aria-hidden") == "false"
    assert skill_modal.locator("[role=dialog]").get_attribute("aria-modal") == "true"
    assert skill_modal.locator(".skill-editor-inner").evaluate(
        "el => parseFloat(getComputedStyle(el).width)"
    ) == pytest.approx(560, abs=0.1)
    page.wait_for_function("document.activeElement?.id === 'csIcon'")
    assert skill_modal.locator("#csIcon").evaluate(
        "el => document.activeElement === el"
    )
    page.keyboard.press("Escape")
    skill_modal.wait_for(state="hidden")
    page.wait_for_function(
        "document.activeElement?.id === 'skillModalOpener'"
    )
    assert skill_modal.get_attribute("aria-hidden") == "true"

    install_opener("catalogModalOpener")
    page.evaluate("window.openCatalogWizard()")
    catalog_modal = page.locator("#catalogWizardModal")
    catalog_modal.wait_for(state="visible")
    assert catalog_modal.locator(".skill-editor-inner").evaluate(
        "el => parseFloat(getComputedStyle(el).width)"
    ) == pytest.approx(480, abs=0.1)
    page.wait_for_function("document.activeElement?.id === 'cwSourceDir'")
    assert catalog_modal.locator("#cwSourceDir").evaluate(
        "el => document.activeElement === el"
    )
    catalog_modal.locator(".ui-close-button").click()
    catalog_modal.wait_for(state="hidden")
    page.wait_for_function(
        "document.activeElement?.id === 'catalogModalOpener'"
    )

    install_opener("bindingModalOpener")
    page.evaluate("window.openCreateBindingModal()")
    binding_modal = page.locator("#createBindingModal")
    binding_modal.wait_for(state="visible")
    assert binding_modal.get_attribute("aria-hidden") == "false"
    page.wait_for_function("document.activeElement?.id === 'cbSkillId'")
    assert binding_modal.locator("#cbSkillId").evaluate(
        "el => document.activeElement === el"
    )
    assert binding_modal.locator("#cbSkillId option").count() >= 1
    binding_modal.click(position={"x": 2, "y": 2})
    binding_modal.wait_for(state="hidden")
    page.wait_for_function(
        "document.activeElement?.id === 'bindingModalOpener'"
    )

    install_opener("skillEditorOpener")
    page.evaluate(
        """
        () => {
          window.getSpSkills = () => [{
            id: 'ui-check',
            icon: '🧪',
            name: 'UI check',
            category: 'custom',
            prompt: 'Keep the modal state unified.',
            ui_config: {},
            ui_extensions: {},
          }];
          window.openSkillEditor('ui-check');
        }
        """
    )
    skill_editor = page.locator("#skillEditorModal")
    skill_editor.wait_for(state="visible")
    assert skill_editor.get_attribute("aria-hidden") == "false"
    assert skill_editor.locator(".ske-panel").get_attribute("role") == "dialog"
    page.wait_for_function("document.activeElement?.id === 'skillEditorContent'")
    assert skill_editor.locator("#skillEditorContent").input_value() == (
        "Keep the modal state unified."
    )
    page.keyboard.press("Escape")
    skill_editor.wait_for(state="hidden")
    page.wait_for_function(
        "document.activeElement?.id === 'skillEditorOpener'"
    )
    assert skill_editor.get_attribute("aria-hidden") == "true"

    install_opener("templateUploadOpener")
    page.evaluate("window.spOpenTemplateUpload('ui-check', 'UI check')")
    template_modal = page.locator("#templateUploadModal")
    template_modal.wait_for(state="visible")
    assert template_modal.get_attribute("aria-hidden") == "false"
    assert template_modal.locator(".template-upload-dialog").get_attribute(
        "role"
    ) == "dialog"
    template_drop_zone = template_modal.locator("#templateDropZone")
    assert template_drop_zone.get_attribute("role") == "button"
    assert template_drop_zone.get_attribute("tabindex") == "0"
    page.wait_for_function("document.activeElement?.id === 'templateDropZone'")
    page.keyboard.press("Escape")
    template_modal.wait_for(state="hidden")
    page.wait_for_function(
        "document.activeElement?.id === 'templateUploadOpener'"
    )
    assert template_modal.get_attribute("aria-hidden") == "true"

    assert console_errors == []
