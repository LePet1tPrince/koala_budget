import React from "react";
import {Link} from "react-router-dom";
import {acceptInviteUrl} from "@/teams/urls";


export const TeamTableRow = function(props) {
  return (
    <tr>
      <td>{props.name}</td>
      <td><a className={'link'} href={props.dashboardUrl}>{gettext("View Dashboard")}</a></td>
      <td className="pg-inline-buttons pg-justify-content-end">
        <Link to={`/edit/${props.slug}`}>
          <button className="pg-button-secondary mx-1">
            <span className="pg-icon"><i className="fa fa-gear" /></span>
            <span className="pg-hidden-mobile-inline">{props.isAdmin ? gettext('Edit') : gettext('View Details')}</span>
          </button>
        </Link>
      </td>
    </tr>
  );
};

export const UserInvitations = function ({invitations, apiUrls, showTitle = true}) {
  if (invitations.length === 0) {
    return <></>
  }
  const viewInvitation = (invitationId) => {
      const url = acceptInviteUrl(apiUrls['teams:accept_invitation'], invitationId);
      window.location.href = url;
  }

  const navigateToManageEmails = () => {
      window.location.href = apiUrls['account_email'];
  }

  return (
    <>
      <div className='table-responsive'>
        <table className="table pg-table">
          <thead>
          <tr>
            <th>{gettext("Team Name")}</th>
            <th/>
          </tr>
          </thead>
          <tbody>
          {invitations.map((invitation) => {
            return (
              <tr key={invitation.id}>
                <td>{invitation.teamName}</td>
                <td className={"pg-inline-buttons pg-justify-content-end"}>
                  {invitation.verified ?
                    <a className="pg-button-secondary" onClick={() => viewInvitation(invitation.id)}>
                      <span>{gettext("View Invitation")}</span>
                    </a>
                    :
                    <a className="pg-button-secondary" onClick={() => navigateToManageEmails()}>
                      <span>{interpolate("Verify \"%s\" to accept", [invitation.email])}</span>
                    </a>
                  }
                </td>
              </tr>
            )
          })}
          </tbody>
        </table>
      </div>
    </>
  )
}


export const TeamList = function(props) {

  return (
    <>
      <section className="app-card">
        <h3 className="pg-subtitle">{gettext("My Teams")}</h3>
        <div className='table-responsive'>
          <table className="table pg-table">
            <thead>
            <tr>
              <th>{gettext("Name")}</th>
              <th/>
              <th/>
            </tr>
            </thead>
            <tbody>
            {
              props.teams.map((team, index) => {
                return <TeamTableRow key={team.id} index={index} {...team} />;
              })
            }
            </tbody>
          </table>
        </div>
        <Link to="/new">
          <button className="mt-2 pg-button-secondary">
            <span className="pg-icon">
              <i className="fa fa-plus"></i>
            </span>
            <span>{gettext("Add Team")}</span>
          </button>
        </Link>
      </section>
      <section className="app-card">
        <h3 className="pg-subtitle">{gettext("Pending Invitations")}</h3>
        <UserInvitations invitations={props.userInvitations} apiUrls={props.apiUrls} />
      </section>
    </>
  );
}
