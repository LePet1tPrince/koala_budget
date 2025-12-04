/* globals gettext */
'use strict';
import React, {useState, useEffect} from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Link, useParams, useNavigate,
} from "react-router-dom";
import TeamDetails from "./TeamDetails";
import {TeamList, UserInvitations} from "./TeamList";
import LoadingScreen from "../utilities/Loading";
import LoadError from "../utilities/LoadError";


const NoTeams = function(props) {
  return (
    <>
      {props.userInvitations ? <NoTeamsPendingInvitationsList {...props} /> : <NoTeamsHero />}
    </>
  );
};

const NoTeamsPendingInvitationsList = function (props) {
  return (
    <section className="app-card">
      <h1 className="pg-title">{gettext("No Teams Yet!")}</h1>
      <h2 className="pg-subtitle">{gettext("But you have some pending invitations.")}</h2>
      <UserInvitations invitations={props.userInvitations} apiUrls={props.apiUrls} />
      <Link to="/new" className="pg-text-muted pg-link mt-3">
          {gettext("Or create a new team")}
      </Link>
    </section>
  )
}

const NoTeamsHero = function (props) {
  return (
    <section className="app-card">
      <div className="pg-columns">
        <div className="pg-column-one-third">
          <img className="img-fluid" alt="Nothing Here" src={STATIC_FILES.undraw_team}/>
        </div>
        <div className="pg-column">
          <h1 className="pg-title">{gettext("No Teams Yet!")}</h1>
          <h2 className="pg-subtitle">{gettext("Create your first team below to get started.")}</h2>
          <p>
            <Link to="/new">
              <button className="pg-button-primary">
                <span className="pg-icon"><i className="fa fa-plus"></i></span>
                <span>{gettext("Create Team")}</span>
              </button>
            </Link>
          </p>
        </div>
      </div>
    </section>
  )
}

const getTeamBySlug = function(teams, slug) {
  for (const team of teams) {
    if (team.slug === slug) {
      return team;
    }
  }
};


const TeamApplication = function(props) {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [teams, setTeams] = useState([]);
  const [userInvitations, setUserInvitations] = useState([]);
  const [editErrors, setEditErrors] = useState({});
  let navigate = useNavigate();

  useEffect(() => {
    props.client.userInvitations().then(result => {
      setUserInvitations(result.results)
    })
    props.client.teamsList().then((result) => {
      initializeTeams(result.results);
    }).catch((error) => {
      console.error(error);
      setLoadError(true);
      setLoading(false);
    });
  }, []);

  const initializeTeams = function (teams) {
    setTeams(teams);
    setLoading(false);
  };

  const handleTeamEditSuccess = () => {
        setTeams([...teams]);
        setEditErrors({});
        navigate('/');
    };

  const handleTeamEditFailed = (error) => {
    error.response.json().then((errors) => {
      setEditErrors(errors);
    });
  }

  const deleteTeam = function(team) {
    const index = teams.indexOf(team);
    let params = {id: team.id}
    props.client.teamsDestroy(params).then((result) => {
      teams.splice(index, 1);
      handleTeamEditSuccess()
    }).catch(handleTeamEditFailed);
  };

  const saveTeam = function(team, name, slug) {
    const teamData = {
      name: name,
    };
    if (Boolean(team)) {
      teamData['slug'] = slug;
      let params = {
        id: team.id,
        patchedTeam: teamData,
      };
      props.client.teamsPartialUpdate(params).then((result) => {
        // find the appropriate item in the list and update in place
        for (let i = 0; i < teams.length; i++) {
          if (teams[i].id === result.id) {
            teams[i] = result;
          }
        }
        handleTeamEditSuccess();
      }).catch(handleTeamEditFailed);
    } else {
      const data = {team: teamData}
      props.client.teamsCreate(data).then((result) => {
        teams.push(result);
        handleTeamEditSuccess()
      }).catch(handleTeamEditFailed);
    }
  };

  const getDefaultView = function() {
    if (loading) {
      return <LoadingScreen/>
    }
    if (loadError) {
      return <LoadError/>
    }
    if (teams.length === 0) {
      return <NoTeams
        userInvitations={userInvitations}
        apiUrls={props.apiUrls}
      />;
    } else {
      return <TeamList
        teams={teams}
        userInvitations={userInvitations}
        user={props.user}
        apiUrls={props.apiUrls}
      />;

    }
  };

  const RenderEditTeam = function() {
    const params = useParams();
    if (loading) {
      return <LoadingScreen />;
    } else {
      const team = getTeamBySlug(teams, params.teamSlug);
      return (
        <TeamDetails save={saveTeam}
                     delete={deleteTeam}
                     returnUrl='/'
                     team={team}
                     client={props.client}
                     apiUrls={props.apiUrls}
                     user={props.user}
                     errors={editErrors}
        />
      );
    }
  };

  return (
    <Routes>
      <Route path="/new" element={
        <TeamDetails save={saveTeam}
                     returnUrl='/'
                     team={null}
                     client={props.client}
                     apiUrls={props.apiUrls}
                     errors={editErrors}
        />
      } />
      <Route path="/edit/:teamSlug" element={ <RenderEditTeam/> } />
      <Route path="/" element={getDefaultView()} />
    </Routes>
  );
};

export default TeamApplication;
