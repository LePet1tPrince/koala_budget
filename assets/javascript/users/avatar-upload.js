import { UsersApi } from 'api-client';
import { getApiConfiguration } from '../api';

/**
 * The profile page's picture upload: preview the chosen file at once, then send it
 * through the users API (`profileAvatarUpload`). The status label's icons come from
 * the page's `<template data-avatar-status="...">` elements, rendered by `{% icon %}`.
 */
const client = new UsersApi(getApiConfiguration(''));

const statusMarkup = (name, text) => {
  const template = document.querySelector(`template[data-avatar-status="${name}"]`);
  const wrapper = document.createElement('span');
  if (template) wrapper.append(template.content.cloneNode(true));
  const label = document.createElement('span');
  label.textContent = text;
  wrapper.append(label);
  return wrapper;
};

const setStatus = (label, name, text, className) => {
  label.replaceChildren(statusMarkup(name, text));
  label.classList.remove('is-active', 'text-success', 'text-error');
  if (className) label.classList.add(className);
};

const updatePreview = (file) => {
  const reader = new FileReader();
  reader.onload = (event) => {
    for (const avatar of document.getElementsByClassName('avatar')) {
      avatar.setAttribute('src', event.target.result);
    }
  };
  reader.readAsDataURL(file);
};

const errorText = async (error) => {
  const payload = error?.response ? await error.response.json().catch(() => ({})) : {};
  const messages = Object.values(payload)
    .flat()
    .filter((message) => typeof message === 'string');
  return messages.join(' ') || gettext('Upload failed!');
};

const upload = async (file, label) => {
  setStatus(label, 'refresh', gettext('Uploading...'), 'is-active');
  try {
    await client.profileAvatarUpload({ avatar: file });
    setStatus(label, 'check', gettext('Success!'), 'text-success');
  } catch (error) {
    const text = await errorText(error);
    setStatus(label, 'times', gettext('Upload failed!'), 'text-error');
    label.title = text;
  }
};

const input = document.getElementById('profile-upload');
const label = document.getElementById('profile-upload-label');
if (input && label) {
  input.addEventListener('change', () => {
    const file = input.files[0];
    if (file) {
      updatePreview(file);
      upload(file, label);
    }
  });
}
