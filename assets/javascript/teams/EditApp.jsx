'use strict';
import React, { useEffect, useState } from 'react';
import TeamDetails from './TeamDetails';
import { getTeamUrl } from './urls';
import LoadingScreen from '../utilities/Loading';
import LoadError from '../utilities/LoadError';

const EditTeamApplication = function (props) {
  const [team, setTeam] = useState(null);
  const [user, setUser] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [recentlySaved, setRecentlySaved] = useState(false);
  const [errors, setErrors] = useState({});

  useEffect(() => {
    Promise.all([props.client.teamsRetrieve({ id: props.teamId }), props.meClient.meRetrieve()])
      .then(([loadedTeam, me]) => {
        setTeam(loadedTeam);
        setUser(me.user);
      })
      .catch((error) => {
        console.error(error);
        setLoadError(true);
      });
  }, [props.teamId]);

  const saveTeam = function (team, name, slug) {
    const params = {
      id: team.id,
      patchedTeam: {
        name: name,
        slug: slug,
      },
    };
    props.client
      .teamsPartialUpdate(params)
      .then((result) => {
        const slugChanged = team.slug !== result.slug;
        if (slugChanged) {
          // if the slug changed we need to do a full-page refresh,
          // because all the links (including navigation) have changed
          window.location = getTeamUrl(props.apiUrls['single_team:manage_team'], result.slug);
        } else {
          setTeam(result);
          setRecentlySaved(true);
          setTimeout(() => setRecentlySaved(false), 3000);
        }
      })
      .catch((error) => {
        error.response.json().then((errors) => {
          setErrors(errors);
        });
      });
  };

  const deleteTeam = function (team) {
    let params = { id: team.id };
    props.client
      .teamsDestroy(params)
      .then(() => {
        window.location = '/';
      })
      .catch((error) => {
        error.response.json().then((errors) => {
          setErrors(errors);
        });
      });
  };

  if (loadError) {
    return <LoadError />;
  }
  if (!team || !user) {
    return <LoadingScreen />;
  }
  return (
    <TeamDetails
      save={saveTeam}
      delete={deleteTeam}
      returnUrl={null}
      recentlySaved={recentlySaved}
      errors={errors}
      client={props.client}
      apiUrls={props.apiUrls}
      team={team}
      user={user}
    />
  );
};

export default EditTeamApplication;
