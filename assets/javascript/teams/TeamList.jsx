import React from "react";
import {Link} from "react-router-dom";
import {acceptInviteUrl} from "@/teams/urls";


export const TeamTableRow = function(props) {
  return (
    <tr>
      <td>{props.name}</td>
      <td><a className={'link'} href={props.dashboardUrl}>{gettext("View Dashboard")}</a></td>
      <td className="flex space-x-1 justify-end">
        <Link to={`/edit/${props.slug}`}>
          <button className="btn btn-outline mx-1">
            <span className="w-6 h-6 inline-flex justify-center items-center"><i className="fa fa-gear" /></span>
            <span className="hidden md:inline-block">{props.isAdmin ? gettext('Edit') : gettext('View Details')}</span>
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
        <table className="table table table-quiet w-full">
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
                <td className={"flex space-x-1 justify-end"}>
                  {invitation.verified ?
                    <a className="btn btn-outline" onClick={() => viewInvitation(invitation.id)}>
                      <span>{gettext("View Invitation")}</span>
                    </a>
                    :
                    <a className="btn btn-outline" onClick={() => navigateToManageEmails()}>
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
        <h3 className="text-xl mb-1">{gettext("My Teams")}</h3>
        <div className='table-responsive'>
          <table className="table table table-quiet w-full">
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
          <button className="mt-2 btn btn-outline">
            <span className="w-6 h-6 inline-flex justify-center items-center">
              <i className="fa fa-plus"></i>
            </span>
            <span>{gettext("Add Team")}</span>
          </button>
        </Link>
      </section>
      <section className="app-card">
        <h3 className="text-xl mb-1">{gettext("Pending Invitations")}</h3>
        <UserInvitations invitations={props.userInvitations} apiUrls={props.apiUrls} />
      </section>
    </>
  );
}
