// App bundle entry — imports all app/* modules
// Each module attaches its API to window.* via backward-compat assignments
import { installErrorBoundary } from '../shared/error-boundary';
import { installStartupMonitor } from '../shared/startup-monitor';
import '../shared/auth';
import '../shared/render-surface';
installStartupMonitor();
installErrorBoundary();

import '../app/main';
import '../app/chat-ui';
import '../app/settings';
import '../app/session-bridge';
import '../app/router';
import '../app/theme';
import '../app/framework';
import '../app/components/koto-settings-panel';
import '../app/components/koto-nav';
import '../app/components/koto-window';
