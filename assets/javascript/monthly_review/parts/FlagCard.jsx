import React from 'react';

import Icon from '../../common/Icon';

const SEVERITY_STYLE = {
  good: { icon: 'check-circle', cls: 'border-success/40 bg-success/5 text-success' },
  info: { icon: 'info', cls: 'border-info/40 bg-info/5 text-info' },
  warn: { icon: 'triangle-alert', cls: 'border-warning/40 bg-warning/5 text-warning' },
  bad: { icon: 'circle-alert', cls: 'border-error/40 bg-error/5 text-error' },
};

/** One rendered `Insight` from the server -- title, optional body, optional action link. */
const FlagCard = ({ insight }) => {
  const style = SEVERITY_STYLE[insight.severity] || SEVERITY_STYLE.info;
  return (
    <div
      className={`rounded-box border p-4 flex gap-3 items-start ${style.cls}`}
      data-testid={`insight-${insight.kind}`}
    >
      <Icon name={style.icon} className="w-5 h-5 shrink-0 mt-0.5" />
      <div className="flex-1">
        <div className="font-medium text-base-content">{insight.title}</div>
        {insight.body && <div className="text-sm text-base-content/70 mt-0.5">{insight.body}</div>}
        {insight.url && (
          <a href={insight.url} className="link link-primary text-sm mt-1 inline-block">
            Fix in Inbox &rarr;
          </a>
        )}
      </div>
    </div>
  );
};

export default FlagCard;
