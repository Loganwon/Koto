// App bundle entry — imports all app/* modules
// Each module attaches its API to window.* via backward-compat assignments
import { installErrorBoundary } from '../shared/error-boundary';
installErrorBoundary();

import '../app/main';
import '../app/chat-ui';
import '../app/marketplace';
import '../app/settings';
import '../app/session-bridge';
import '../app/router';
import '../app/theme';
import '../app/framework';
