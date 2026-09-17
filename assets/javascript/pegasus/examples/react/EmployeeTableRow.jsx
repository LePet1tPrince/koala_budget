import React from "react";
import {Link} from "react-router-dom";
import Icon from '../../../common/Icon';

const EmployeeTableRow = function (props) {
  const formatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  });
  return (
    <tr>
      <td>{props.name}</td>
      <td>{props.department}</td>
      <td className="text-right">{ formatter.format(props.salary) }</td>
      <td className="flex space-x-1 justify-end">
          <Link to={`edit/${props.id}`}>
            <div className="btn btn-outline">
              <span className="w-6 h-6 inline-flex justify-center items-center"><Icon name="edit" className="inline-block shrink-0 w-4 h-4" /></span>
              <span className="hidden md:inline-block">Edit</span>
            </div>
          </Link>
          <a onClick={() => props.delete(props.index)}>
            <div className="btn btn-outline btn-error">
              <span className="w-6 h-6 inline-flex justify-center items-center"><Icon name="times" className="inline-block shrink-0 w-4 h-4" /></span>
              <span className="hidden md:inline-block">Delete</span>
            </div>
          </a>
      </td>
    </tr>
  );
}

export default EmployeeTableRow;
