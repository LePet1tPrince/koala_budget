import {BankFeedApi} from "api-client";
import {getApiConfiguration} from "../api";

export function getBankFeedApiClient(serverBaseUrl) {
  return new BankFeedApi(getApiConfiguration(serverBaseUrl));
}
