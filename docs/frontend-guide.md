# Frontend Guide

This document describes the frontend architecture for Koala Budget.

## Overview

The frontend uses a hybrid approach:

1. **Django Templates** - Server-rendered HTML for most pages
2. **Inline React/Alpine** - Interactive components within templates (`/assets/javascript/`)
3. **Standalone React SPA** - Authentication flows (`/frontend/`)

All JavaScript is bundled by Vite and served via `django-vite`.

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Build Tool | Vite 7.x | Fast bundling with HMR |
| Primary Framework | React 19.x | Complex interactive UIs |
| Secondary | Alpine.js 3.x | Simple page interactions |
| Styling | Tailwind CSS 4.x | Utility-first CSS |
| Components | DaisyUI 5.x | Pre-built Tailwind components |
| Data Tables | Material Tables from Material UI | Powerful table components |
| Type System | TypeScript 5.x | Type safety |

## Project Structure

```
koala_budget_pegasus/
├── assets/                      # Source files (bundled by Vite)
│   ├── javascript/
│   │   ├── app.js              # Main entry point
│   │   ├── site.js             # Marketing site entry
│   │   ├── bank_feed/          # Bank feed React components
│   │   │   ├── BankFeedLine.tsx
│   │   │   └── ...
│   │   ├── budget/             # Budget components
│   │   ├── chat/               # Chat interface
│   │   ├── reports/            # Report visualizations
│   │   └── teams/              # Team management
│   └── styles/
│       ├── app.css             # Main app styles
│       └── site.css            # Marketing site styles
│
├── frontend/                    # Standalone React SPA
│   ├── src/
│   │   ├── main.tsx            # Entry point
│   │   ├── index.css           # Global styles
│   │   ├── pages/              # Page components
│   │   │   ├── Login.tsx
│   │   │   ├── Signup.tsx
│   │   │   └── ...
│   │   ├── components/         # Shared components
│   │   │   └── DashboardLayout.tsx
│   │   ├── layouts/            # Layout templates
│   │   │   └── AuthLayout.tsx
│   │   ├── routes/             # Router configuration
│   │   │   └── index.tsx
│   │   ├── allauth_auth/       # Auth context & hooks
│   │   │   ├── AuthContext.jsx
│   │   │   └── hooks.js
│   │   ├── api/                # API utilities
│   │   │   └── utils.tsx
│   │   └── lib/                # Library wrappers
│   │       └── allauth.js
│   ├── vite.config.ts
│   └── package.json
│
├── api-client/                  # Generated TypeScript API client
│   ├── apis/
│   │   ├── BankFeedApi.ts
│   │   ├── JournalApi.ts
│   │   └── ...
│   ├── models/
│   └── runtime.ts
│
├── static/                      # Built output (gitignored)
│   ├── js/
│   ├── css/
│   └── .vite/manifest.json
│
└── templates/                   # Django templates
    └── *.html
```

## Vite Configuration

Entry points defined in `vite.config.ts`:

```typescript
build: {
  rollupOptions: {
    input: {
      'site-base-css': 'assets/styles/site-base.css',
      'site-tailwind-css': 'assets/styles/site-tailwind.css',
      'site': 'assets/javascript/site.js',
      'app': 'assets/javascript/app.js',
      'teams': 'assets/javascript/teams/index.tsx',
      'chat': 'assets/javascript/chat.js',
      'reports': 'assets/javascript/reports.js',
      'bank-feed': 'assets/javascript/bank_feed/BankFeedLine.tsx',
      // ...
    }
  }
}
```

## Django Template Integration

### Loading Vite Assets

```html
{% load django_vite %}

<!DOCTYPE html>
<html>
<head>
  {% vite_asset 'assets/styles/app.css' %}
</head>
<body>
  <!-- Content -->

  {% vite_react_refresh %}  {# Required for React HMR #}
  {% vite_asset 'assets/javascript/app.js' %}
</body>
</html>
```

### Mounting React Components

Template provides a mount point and passes data:

```html
{# templates/bank_feed/bank_feed.html #}
{% load django_vite %}

<div id="bank-feed-app"></div>

<script>
  window.BANK_FEED_PROPS = {
    apiUrls: {
      feed: "{% url 'bank_feed:api-feed-list' team_slug=team.slug %}",
      categorize: "{% url 'bank_feed:api-feed-categorize' team_slug=team.slug %}"
    },
    accounts: {{ accounts_json|safe }},
    categories: {{ categories_json|safe }}
  };
</script>

{% vite_react_refresh %}
{% vite_asset 'assets/javascript/bank_feed/BankFeedLine.tsx' %}
```

React component mounts itself:

```typescript
// assets/javascript/bank_feed/BankFeedLine.tsx
import { createRoot } from 'react-dom/client';

const container = document.getElementById('bank-feed-app');
if (container) {
  const root = createRoot(container);
  root.render(<BankFeedApp {...window.BANK_FEED_PROPS} />);
}
```

## State Management

### React Context (Primary)

Used for global state like authentication:

```typescript
// frontend/src/allauth_auth/AuthContext.jsx
const AuthContext = createContext();

export function AuthContextProvider({ children }) {
  const [auth, setAuth] = useState(null);
  const [config, setConfig] = useState(null);

  // Listen for auth change events
  useEffect(() => {
    const handler = (e) => setAuth(e.detail);
    document.addEventListener('allauth.auth.change', handler);
    return () => document.removeEventListener('allauth.auth.change', handler);
  }, []);

  return (
    <AuthContext.Provider value={{ auth, config }}>
      {children}
    </AuthContext.Provider>
  );
}
```

### Custom Hooks

```typescript
// Get current user
const user = useUser();

// Get auth status
const { isAuthenticated, requiresReauthentication } = useAuthInfo();

// Get full auth object
const auth = useAuth();

// Get app config
const config = useConfig();
```

### Component Local State

For component-specific state:

```typescript
function TransactionList() {
  const [transactions, setTransactions] = useState([]);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [isLoading, setIsLoading] = useState(true);

  // ...
}
```

## Routing

### Standalone SPA Routes

```typescript
// frontend/src/routes/index.tsx
const routes = createBrowserRouter([
  {
    path: '/',
    element: <Root />,
    children: [
      { path: '/', element: <App /> },

      // Anonymous routes (redirect if logged in)
      {
        element: <AnonymousRoute />,
        children: [
          { path: '/account/login', element: <Login /> },
          { path: '/account/signup', element: <Signup /> },
        ]
      },

      // Protected routes (redirect if not logged in)
      {
        element: <AuthenticatedRoute />,
        children: [
          {
            path: '/dashboard',
            element: <DashboardLayout />,
            children: [
              { path: 'profile', element: <Profile /> },
            ]
          }
        ]
      }
    ]
  }
]);
```

### Route Protection Components

```typescript
// Redirect to login if not authenticated
function AuthenticatedRoute() {
  const { isAuthenticated } = useAuthInfo();
  if (!isAuthenticated) return <Navigate to="/account/login" />;
  return <Outlet />;
}

// Redirect to dashboard if already authenticated
function AnonymousRoute() {
  const { isAuthenticated } = useAuthInfo();
  if (isAuthenticated) return <Navigate to="/dashboard" />;
  return <Outlet />;
}
```

## API Client Usage

### Configuration

```typescript
// frontend/src/api/utils.tsx
import { Configuration } from 'api-client';

export function getApiConfiguration(): Configuration {
  return new Configuration({
    basePath: import.meta.env.VITE_APP_BASE_URL || '',
    credentials: 'include',  // Include cookies
    headers: {
      'X-CSRFToken': getCSRFToken()
    }
  });
}

function getCSRFToken(): string {
  return document.cookie
    .split('; ')
    .find(row => row.startsWith('csrftoken='))
    ?.split('=')[1] || '';
}
```

### Making API Calls

```typescript
import { BankFeedApi } from 'api-client';
import { getApiConfiguration } from '../api/utils';

function BankFeedComponent() {
  const [feed, setFeed] = useState([]);

  useEffect(() => {
    const api = new BankFeedApi(getApiConfiguration());
    api.feedList().then(response => {
      setFeed(response.results);
    });
  }, []);

  const handleCategorize = async (id: number, categoryId: number) => {
    const api = new BankFeedApi(getApiConfiguration());
    await api.feedCategorize({
      categorizeRequest: { id, categoryId }
    });
    // Refresh feed
  };
}
```

## Styling

### Tailwind CSS

Use utility classes directly:

```tsx
<div className="flex items-center gap-4 p-4 bg-base-100 rounded-lg shadow">
  <span className="text-lg font-semibold">{title}</span>
  <button className="btn btn-primary btn-sm">Action</button>
</div>
```

### DaisyUI Components

Pre-built component classes:

```tsx
// Buttons
<button className="btn">Default</button>
<button className="btn btn-primary">Primary</button>
<button className="btn btn-secondary btn-sm">Small Secondary</button>

// Cards
<div className="card bg-base-100 shadow-xl">
  <div className="card-body">
    <h2 className="card-title">Title</h2>
    <p>Content</p>
  </div>
</div>

// Tables
<table className="table table-zebra">
  <thead>
    <tr><th>Name</th><th>Amount</th></tr>
  </thead>
  <tbody>
    <tr><td>Item</td><td>$100</td></tr>
  </tbody>
</table>

// Modals
<dialog id="my_modal" className="modal">
  <div className="modal-box">
    <h3>Modal Title</h3>
    <p>Content</p>
  </div>
  <form method="dialog" className="modal-backdrop">
    <button>close</button>
  </form>
</dialog>
```

### Color Palette

Use DaisyUI semantic colors:

```tsx
// Primary actions
className="bg-primary text-primary-content"

// Secondary elements
className="bg-secondary text-secondary-content"

// Backgrounds
className="bg-base-100"  // Main background
className="bg-base-200"  // Slightly darker
className="bg-base-300"  // Card/panel background

// Status colors
className="text-success"  // Green
className="text-warning"  // Yellow
className="text-error"    // Red
className="text-info"     // Blue
```


## Development Workflow

### Start Dev Server

```bash
# Start all services (includes Vite with HMR)
make start

# Or run Vite separately
make npm-dev
```

### Build for Production

```bash
make npm-build
```

### Type Checking

```bash
make npm-type-check
```

### Adding Dependencies

```bash
# Add package
make npm-install package-name

# Remove package
make npm-uninstall package-name
```

## Best Practices

### Component Organization

- Keep components small and focused
- Use TypeScript for type safety
- Extract reusable logic into hooks
- Co-locate related files

### State Management

- Use local state for component-specific data
- Use context for app-wide state (auth, theme)
- Avoid prop drilling - use context when needed
- Keep API calls in useEffect or event handlers

### Styling

- Use DaisyUI components when available
- Fall back to Tailwind utilities
- Stick to the DaisyUI color palette
- Use semantic color names (primary, error) not raw colors

### API Integration

- Always use the generated TypeScript client
- Handle loading and error states
- Show appropriate feedback to users
- Use optimistic updates for better UX

### Performance

- Lazy load heavy components
- Memoize expensive calculations
- Use pagination for long lists
- Avoid unnecessary re-renders
