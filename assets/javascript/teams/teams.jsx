'use strict';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { getApiConfiguration } from '../api';
import TeamApplication from './App';
import { BrowserRouter } from 'react-router-dom';
import { ApiApi, TeamsApi } from 'api-client';

const domContainer = document.querySelector('#team-content');
const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);
// Same origin as the page: the Site domain (`server_url`) can differ from the host serving it.
const configuration = getApiConfiguration(window.location.origin);
const apiClient = new TeamsApi(configuration);
const meClient = new ApiApi(configuration);

const root = createRoot(domContainer);
root.render(
  <BrowserRouter basename={urlBase}>
    <TeamApplication client={apiClient} meClient={meClient} urlBase={urlBase} apiUrls={apiUrls} />
  </BrowserRouter>,
);
