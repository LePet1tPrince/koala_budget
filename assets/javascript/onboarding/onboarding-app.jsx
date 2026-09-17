import React from 'react';
import { createRoot } from 'react-dom/client';

import { getOnboardingApi } from './api';
import OnboardingShell from './OnboardingShell';

const mount = document.getElementById('onboarding-app');
const props = JSON.parse(document.getElementById('onboarding-props').textContent);

createRoot(mount).render(<OnboardingShell props={{ ...props, api: getOnboardingApi(props.urls) }} />);
