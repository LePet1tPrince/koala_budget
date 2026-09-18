import React from 'react';
import { createRoot } from 'react-dom/client';

import { getMonthlyReviewApi } from './api';
import ReviewApp from './ReviewApp';

const mount = document.getElementById('monthly-review-app');
const props = JSON.parse(document.getElementById('monthly-review-props').textContent);

createRoot(mount).render(<ReviewApp props={{ ...props, api: getMonthlyReviewApi(props.urls, props.month) }} />);
