import {BankFeedApi, PlaidApi, JournalApi} from "api-client";
import {getApiConfiguration} from "../api";

export function getBankFeedApiClient(serverBaseUrl) {
  return new BankFeedApi(getApiConfiguration(serverBaseUrl));
}

export function getPlaidApiClient(serverBaseUrl) {
  return new PlaidApi(getApiConfiguration(serverBaseUrl));
}

export function getJournalApiClient(serverBaseUrl) {
  return new JournalApi(getApiConfiguration(serverBaseUrl));
}
