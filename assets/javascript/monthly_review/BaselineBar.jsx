import React from 'react';

/** The 1m/3m/6m/12m/all-time comparison toggle, rendered on steps 2-8 and the dashboard. */
const BaselineBar = ({ baselines, order, value, onChange }) => {
  if (!order || !order.length) return null;
  return (
    <div className="join" data-testid="baseline-bar">
      {order.map((id) => (
        <button
          key={id}
          type="button"
          className={`btn btn-sm join-item ${value === id ? 'btn-primary' : 'btn-outline'}`}
          onClick={() => onChange(id)}
          data-testid={`baseline-${id}`}
        >
          {baselines[id].short}
        </button>
      ))}
    </div>
  );
};

export default BaselineBar;
