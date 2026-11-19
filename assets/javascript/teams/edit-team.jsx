'use strict';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { getApiConfiguration } from '../api';
import EditTeamApplication from './EditApp';
import { ApiApi, TeamsApi } from 'api-client';

const domContainer = document.querySelector('#manage-team-content');

// Only the team's id is in the page; the team and the user are loaded from the API.
const teamId = JSON.parse(document.getElementById('team-id').textContent);
const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);
const serverUrl = JSON.parse(document.getElementById('server-url').textContent);
const configuration = getApiConfiguration(serverUrl);
const apiClient = new TeamsApi(configuration);
const meClient = new ApiApi(configuration);

const root = createRoot(domContainer);
root.render(<EditTeamApplication client={apiClient} meClient={meClient} teamId={teamId} apiUrls={apiUrls} />);
