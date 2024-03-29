"""
:synopsis: most ajax processors for askbot

This module contains most (but not all) processors for Ajax requests.
Not so clear if this subdivision was necessary as separation of Ajax and non-ajax views
is not always very clean.
"""
import datetime
import logging
from bs4 import BeautifulSoup
from django.conf import settings as django_settings
from django.core import exceptions
#from django.core.management import call_command
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import HttpResponseRedirect
from django.http import HttpResponseForbidden
from django.forms import ValidationError, IntegerField, CharField
from django.shortcuts import get_object_or_404
from django.views.decorators import csrf
from django.utils import simplejson
from django.utils.html import escape
from django.utils.translation import ugettext as _
from django.utils.translation import string_concat
from askbot.utils.slug import slugify
from askbot import models
from askbot import forms
from askbot.conf import should_show_sort_by_relevance
from askbot.conf import settings as askbot_settings
from askbot.models.tag import get_global_group
from askbot.utils import category_tree
from askbot.utils import decorators
from askbot.utils import url_utils
from askbot.utils.forms import get_db_object_or_404
from askbot import mail
from django.template import Context
from askbot.skins.loaders import render_into_skin, get_template
from askbot.skins.loaders import render_into_skin_as_string
from askbot.skins.loaders import render_text_into_skin
from askbot import const


@csrf.csrf_exempt
def manage_inbox(request):
    """delete, mark as new or seen user's
    response memo objects, excluding flags
    request data is memo_list  - list of integer id's of the ActivityAuditStatus items
    and action_type - string - one of delete|mark_new|mark_seen
    """

    response_data = dict()
    try:
        if request.is_ajax():
            if request.method == 'POST':
                post_data = simplejson.loads(request.raw_post_data)
                if request.user.is_authenticated():
                    activity_types = const.RESPONSE_ACTIVITY_TYPES_FOR_DISPLAY
                    activity_types += (
                        const.TYPE_ACTIVITY_MENTION,
                        const.TYPE_ACTIVITY_MARK_OFFENSIVE,
                        const.TYPE_ACTIVITY_MODERATED_NEW_POST,
                        const.TYPE_ACTIVITY_MODERATED_POST_EDIT
                    )
                    user = request.user
                    memo_set = models.ActivityAuditStatus.objects.filter(
                        id__in = post_data['memo_list'],
                        activity__activity_type__in = activity_types,
                        user = user
                    )

                    action_type = post_data['action_type']
                    if action_type == 'delete':
                        memo_set.delete()
                    elif action_type == 'mark_new':
                        memo_set.update(status = models.ActivityAuditStatus.STATUS_NEW)
                    elif action_type == 'mark_seen':
                        memo_set.update(status = models.ActivityAuditStatus.STATUS_SEEN)
                    elif action_type == 'remove_flag':
                        for memo in memo_set:
                            activity_type = memo.activity.activity_type
                            if activity_type == const.TYPE_ACTIVITY_MARK_OFFENSIVE:
                                request.user.flag_post(
                                    post = memo.activity.content_object,
                                    cancel_all = True
                                )
                            elif activity_type in \
                                (
                                    const.TYPE_ACTIVITY_MODERATED_NEW_POST,
                                    const.TYPE_ACTIVITY_MODERATED_POST_EDIT
                                ):
                                post_revision = memo.activity.content_object
                                request.user.approve_post_revision(post_revision)
                                memo.delete()

                    #elif action_type == 'close':
                    #    for memo in memo_set:
                    #        if memo.activity.content_object.post_type == "exercise":
                    #            request.user.close_exercise(exercise = memo.activity.content_object, reason = 7)
                    #            memo.delete()
                    elif action_type == 'delete_post':
                        for memo in memo_set:
                            content_object = memo.activity.content_object
                            if isinstance(content_object, models.PostRevision):
                                post = content_object.post
                            else:
                                post = content_object
                            request.user.delete_post(post)
                            reject_reason = models.PostFlagReason.objects.get(
                                                    id = post_data['reject_reason_id']
                                                )
                            template = get_template('email/rejected_post.html')
                            data = {
                                    'post': post.html,
                                    'reject_reason': reject_reason.details.html
                                   }
                            body_text = template.render(Context(data))
                            mail.send_mail(
                                subject_line = _('your post was not accepted'),
                                body_text = unicode(body_text),
                                recipient_list = [post.author.email,]
                            )
                            memo.delete()

                    user.update_response_counts()

                    response_data['success'] = True
                    data = simplejson.dumps(response_data)
                    return HttpResponse(data, mimetype="application/json")
                else:
                    raise exceptions.PermissionDenied(
                        _('Sorry, but anonymous users cannot access the inbox')
                    )
            else:
                raise exceptions.PermissionDenied('must use POST request')
        else:
            #todo: show error page but no-one is likely to get here
            return HttpResponseRedirect(reverse('index'))
    except Exception, e:
        message = unicode(e)
        if message == '':
            message = _('Oops, apologies - there was some error')
        response_data['message'] = message
        response_data['success'] = False
        data = simplejson.dumps(response_data)
        return HttpResponse(data, mimetype="application/json")


def process_vote(user = None, vote_direction = None, post = None):
    """function (non-view) that actually processes user votes
    - i.e. up- or down- votes

    in the future this needs to be converted into a real view function
    for that url and javascript will need to be adjusted

    also in the future make keys in response data be more meaningful
    right now they are kind of cryptic - "status", "count"
    """
    if user.is_anonymous():
        raise exceptions.PermissionDenied(_(
            'Sorry, anonymous users cannot vote'
        ))

    user.assert_can_vote_for_post(post = post, direction = vote_direction)
    vote = user.get_old_vote_for_post(post)
    response_data = {}
    if vote != None:
        user.assert_can_revoke_old_vote(vote)
        score_delta = vote.cancel()
        response_data['count'] = post.points+ score_delta
        response_data['status'] = 1 #this means "cancel"

    else:
        #this is a new vote
        votes_left = user.get_unused_votes_today()
        if votes_left <= 0:
            raise exceptions.PermissionDenied(
                            _('Sorry you ran out of votes for today')
                        )

        votes_left -= 1
        if votes_left <= \
            askbot_settings.VOTES_LEFT_WARNING_THRESHOLD:
            msg = _('You have %(votes_left)s votes left for today') \
                    % {'votes_left': votes_left }
            response_data['message'] = msg

        if vote_direction == 'up':
            vote = user.upvote(post = post)
        else:
            vote = user.downvote(post = post)

        response_data['count'] = post.points
        response_data['status'] = 0 #this means "not cancel", normal operation

    response_data['success'] = 1

    return response_data


@csrf.csrf_exempt
def vote(request, id):
    """
    todo: this subroutine needs serious refactoring it's too long and is hard to understand

    vote_type:
        acceptProblem : 0,
        exerciseUpVote : 1,
        exerciseDownVote : 2,
        favorite : 4,
        problemUpVote: 5,
        problemDownVote:6,
        offensiveExercise : 7,
        remove offensiveExercise flag : 7.5,
        remove all offensiveExercise flag : 7.6,
        offensiveProblem:8,
        remove offensiveProblem flag : 8.5,
        remove all offensiveProblem flag : 8.6,
        removeExercise: 9,
        removeProblem:10
        exerciseSubscribeUpdates:11
        exerciseUnSubscribeUpdates:12

    accept problem code:
        response_data['allowed'] = -1, Accept his own problem   0, no allowed - Anonymous    1, Allowed - by default
        response_data['success'] =  0, failed                                               1, Success - by default
        response_data['status']  =  0, By default                       1, Problem has been accepted already(Cancel)

    vote code:
        allowed = -3, Don't have enough votes left
                  -2, Don't have enough reputation score
                  -1, Vote his own post
                   0, no allowed - Anonymous
                   1, Allowed - by default
        status  =  0, By default
                   1, Cancel
                   2, Vote is too old to be canceled

    offensive code:
        allowed = -3, Don't have enough flags left
                  -2, Don't have enough reputation score to do this
                   0, not allowed
                   1, allowed
        status  =  0, by default
                   1, can't do it again
    """
    response_data = {
        "allowed": 1,
        "success": 1,
        "status" : 0,
        "count"  : 0,
        "message" : ''
    }

    try:
        if request.is_ajax() and request.method == 'POST':
            vote_type = request.POST.get('type')
        else:
            raise Exception(_('Sorry, something is not right here...'))

        if vote_type == '0':
            if request.user.is_authenticated():
                problem_id = request.POST.get('postId')
                problem = get_object_or_404(models.Post, post_type='problem', id = problem_id)
                # make sure exercise author is current user
                if problem.accepted():
                    request.user.unaccept_best_problem(problem)
                    response_data['status'] = 1 #cancelation
                else:
                    request.user.accept_best_problem(problem)

                ####################################################################
                problem.thread.update_summary_html() # regenerate exercise/thread summary html
                ####################################################################

            else:
                raise exceptions.PermissionDenied(
                        _('Sorry, but anonymous users cannot accept problems')
                    )

        elif vote_type in ('1', '2', '5', '6'):#Q&A up/down votes

            ###############################
            # all this can be avoided with
            # better query parameters
            vote_direction = 'up'
            if vote_type in ('2','6'):
                vote_direction = 'down'

            if vote_type in ('5', '6'):
                #todo: fix this weirdness - why postId here
                #and not with exercise?
                id = request.POST.get('postId')
                post = get_object_or_404(models.Post, post_type='problem', id=id)
            else:
                post = get_object_or_404(models.Post, post_type='exercise', id=id)
            #
            ######################

            response_data = process_vote(
                                        user = request.user,
                                        vote_direction = vote_direction,
                                        post = post
                                    )

            ####################################################################
            if vote_type in ('1', '2'): # up/down-vote exercise
                post.thread.update_summary_html() # regenerate exercise/thread summary html
            ####################################################################

        elif vote_type in ['7', '8']:
            #flag exercise or problem
            if vote_type == '7':
                post = get_object_or_404(models.Post, post_type='exercise', id=id)
            if vote_type == '8':
                id = request.POST.get('postId')
                post = get_object_or_404(models.Post, post_type='problem', id=id)

            request.user.flag_post(post)

            response_data['count'] = post.offensive_flag_count
            response_data['success'] = 1

        elif vote_type in ['7.5', '8.5']:
            #flag exercise or problem
            if vote_type == '7.5':
                post = get_object_or_404(models.Post, post_type='exercise', id=id)
            if vote_type == '8.5':
                id = request.POST.get('postId')
                post = get_object_or_404(models.Post, post_type='problem', id=id)

            request.user.flag_post(post, cancel = True)

            response_data['count'] = post.offensive_flag_count
            response_data['success'] = 1

        elif vote_type in ['7.6', '8.6']:
            #flag exercise or problem
            if vote_type == '7.6':
                post = get_object_or_404(models.Post, id=id)
            if vote_type == '8.6':
                id = request.POST.get('postId')
                post = get_object_or_404(models.Post, id=id)

            request.user.flag_post(post, cancel_all = True)

            response_data['count'] = post.offensive_flag_count
            response_data['success'] = 1

        elif vote_type in ['9', '10']:
            #delete exercise or problem
            post = get_object_or_404(models.Post, post_type='exercise', id=id)
            if vote_type == '10':
                id = request.POST.get('postId')
                post = get_object_or_404(models.Post, post_type='problem', id=id)

            if post.deleted == True:
                request.user.restore_post(post = post)
            else:
                request.user.delete_post(post = post)

        elif request.is_ajax() and request.method == 'POST':

            if not request.user.is_authenticated():
                response_data['allowed'] = 0
                response_data['success'] = 0

            exercise = get_object_or_404(models.Post, post_type='exercise', id=id)
            vote_type = request.POST.get('type')

            #accept problem
            if vote_type == '4':
                fave = request.user.toggle_favorite_exercise(exercise)
                response_data['count'] = models.FavoriteExercise.objects.filter(thread = exercise.thread).count()
                if fave == False:
                    response_data['status'] = 1

            elif vote_type == '11':#subscribe q updates
                user = request.user
                if user.is_authenticated():
                    if user not in exercise.thread.followed_by.all():
                        user.follow_exercise(exercise)
                        if askbot_settings.EMAIL_VALIDATION == True \
                            and user.email_isvalid == False:

                            response_data['message'] = \
                                    _(
                                        'Your subscription is saved, but email address '
                                        '%(email)s needs to be validated, please see '
                                        '<a href="%(details_url)s">more details here</a>'
                                    ) % {'email':user.email,'details_url':reverse('faq') + '#validate'}

                    subscribed = user.subscribe_for_followed_exercise_alerts()
                    if subscribed:
                        if 'message' in response_data:
                            response_data['message'] += '<br/>'
                        response_data['message'] += _('email update frequency has been set to daily')
                    #response_data['status'] = 1
                    #responst_data['allowed'] = 1
                else:
                    pass
                    #response_data['status'] = 0
                    #response_data['allowed'] = 0
            elif vote_type == '12':#unsubscribe q updates
                user = request.user
                if user.is_authenticated():
                    user.unfollow_exercise(exercise)
        else:
            response_data['success'] = 0
            response_data['message'] = u'Request mode is not supported. Please try again.'

        if vote_type not in (1, 2, 4, 5, 6, 11, 12):
            #favorite or subscribe/unsubscribe
            #upvote or downvote exercise or problem - those
            #are handled within user.upvote and user.downvote
            post = models.Post.objects.get(id = id)
            post.thread.invalidate_cached_data()

        data = simplejson.dumps(response_data)

    except Exception, e:
        response_data['message'] = unicode(e)
        response_data['success'] = 0
        data = simplejson.dumps(response_data)
    return HttpResponse(data, mimetype="application/json")

#internally grouped views - used by the tagging system
@csrf.csrf_exempt
@decorators.post_only
@decorators.ajax_login_required
def mark_tag(request, **kwargs):#tagging system
    action = kwargs['action']
    post_data = simplejson.loads(request.raw_post_data)
    raw_tagnames = post_data['tagnames']
    reason = post_data['reason']
    assert reason in ('good', 'bad', 'subscribed')
    #separate plain tag names and wildcard tags

    tagnames, wildcards = forms.clean_marked_tagnames(raw_tagnames)
    cleaned_tagnames, cleaned_wildcards = request.user.mark_tags(
                                                            tagnames,
                                                            wildcards,
                                                            reason = reason,
                                                            action = action
                                                        )

    #lastly - calculate tag usage counts
    tag_usage_counts = dict()
    for name in tagnames:
        if name in cleaned_tagnames:
            tag_usage_counts[name] = 1
        else:
            tag_usage_counts[name] = 0

    for name in wildcards:
        if name in cleaned_wildcards:
            tag_usage_counts[name] = models.Tag.objects.filter(
                                        name__startswith = name[:-1]
                                    ).count()
        else:
            tag_usage_counts[name] = 0

    return HttpResponse(simplejson.dumps(tag_usage_counts), mimetype="application/json")

#@decorators.ajax_only
@decorators.get_only
def get_tags_by_wildcard(request):
    """returns an json encoded array of tag names
    in the response to a wildcard tag name
    """
    wildcard = request.GET.get('wildcard', None)
    if wildcard is None:
        raise Http404

    matching_tags = models.Tag.objects.get_by_wildcards( [wildcard,] )
    count = matching_tags.count()
    names = matching_tags.values_list('name', flat = True)[:20]
    re_data = simplejson.dumps({'tag_count': count, 'tag_names': list(names)})
    return HttpResponse(re_data, mimetype = 'application/json')

@decorators.get_only
def get_thread_shared_users(request):
    """returns snippet of html with users"""
    thread_id = request.GET['thread_id']
    thread_id = IntegerField().clean(thread_id)
    thread = models.Thread.objects.get(id=thread_id)
    users = thread.get_users_shared_with()
    data = {
        'users': users,
    }
    html = render_into_skin_as_string('widgets/user_list.html', data, request)
    re_data = simplejson.dumps({
        'html': html,
        'users_count': users.count(),
        'success': True
    })
    return HttpResponse(re_data, mimetype='application/json')

@decorators.get_only
def get_thread_shared_groups(request):
    """returns snippet of html with groups"""
    thread_id = request.GET['thread_id']
    thread_id = IntegerField().clean(thread_id)
    thread = models.Thread.objects.get(id=thread_id)
    groups = thread.get_groups_shared_with()
    data = {'groups': groups}
    html = render_into_skin_as_string('widgets/groups_list.html', data, request)
    re_data = simplejson.dumps({
        'html': html,
        'groups_count': groups.count(),
        'success': True
    })
    return HttpResponse(re_data, mimetype='application/json')

@decorators.ajax_only
def get_html_template(request):
    """returns rendered template"""
    template_name = request.REQUEST.get('template_name', None)
    allowed_templates = (
        'widgets/tag_category_selector.html',
    )
    #have allow simple context for the templates
    if template_name not in allowed_templates:
        raise Http404
    return {
        'html': get_template(template_name).render()
    }

@decorators.get_only
def get_tag_list(request):
    """returns tags to use in the autocomplete
    function
    """
    tags = models.Tag.objects.filter(
                        deleted = False,
                        status = models.Tag.STATUS_ACCEPTED
                    )

    tag_names = tags.values_list(
                        'name', flat = True
                    )

    output = '\n'.join(map(escape, tag_names))
    return HttpResponse(output, mimetype = 'text/plain')

@decorators.get_only
def load_object_description(request):
    """returns text of the object description in text"""
    obj = get_db_object_or_404(request.GET)#askbot forms utility
    text = getattr(obj.description, 'text', '').strip()
    return HttpResponse(text, mimetype = 'text/plain')

@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
@decorators.admins_only
def save_object_description(request):
    """if object description does not exist,
    creates a new record, otherwise edits an existing
    one"""
    obj = get_db_object_or_404(request.POST)
    text = request.POST['text']
    if obj.description:
        request.user.edit_post(obj.description, body_text=text)
    else:
        request.user.post_object_description(obj, body_text=text)
    return {'html': obj.description.html}

@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
def rename_tag(request):
    if request.user.is_anonymous() \
        or not request.user.is_administrator_or_moderator():
        raise exceptions.PermissionDenied()
    post_data = simplejson.loads(request.raw_post_data)
    to_name = forms.clean_tag(post_data['to_name'])
    from_name = forms.clean_tag(post_data['from_name'])
    path = post_data['path']

    #kwargs = {'from': old_name, 'to': new_name}
    #call_command('rename_tags', **kwargs)

    tree = category_tree.get_data()
    category_tree.rename_category(
        tree,
        from_name = from_name,
        to_name = to_name,
        path = path
    )
    category_tree.save_data(tree)

@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
def delete_tag(request):
    """todo: actually delete tags
    now it is only deletion of category from the tree"""
    if request.user.is_anonymous() \
        or not request.user.is_administrator_or_moderator():
        raise exceptions.PermissionDenied()
    post_data = simplejson.loads(request.raw_post_data)
    tag_name = forms.clean_tag(post_data['tag_name'])
    path = post_data['path']
    tree = category_tree.get_data()
    category_tree.delete_category(tree, tag_name, path)
    category_tree.save_data(tree)
    return {'tree_data': tree}

@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
def add_tag_category(request):
    """adds a category at the tip of a given path expects
    the following keys in the ``request.POST``
    * path - array starting with zero giving path to
      the category page where to add the category
    * new_category_name - string that must satisfy the
      same requiremets as a tag

    return json with the category tree data
    todo: switch to json stored in the live settings
    now we have indented input
    """
    if request.user.is_anonymous() \
        or not request.user.is_administrator_or_moderator():
        raise exceptions.PermissionDenied()

    post_data = simplejson.loads(request.raw_post_data)
    category_name = forms.clean_tag(post_data['new_category_name'])
    path = post_data['path']

    tree = category_tree.get_data()

    if category_tree.path_is_valid(tree, path) == False:
        raise ValueError('category insertion path is invalid')

    new_path = category_tree.add_category(tree, category_name, path)
    category_tree.save_data(tree)
    return {
        'tree_data': tree,
        'new_path': new_path
    }


@decorators.get_only
def get_groups_list(request):
    """returns names of group tags
    for the autocomplete function"""
    global_group = get_global_group()
    groups = models.Group.objects.exclude_personal()
    group_names = groups.exclude(
                        name=global_group.name
                    ).values_list(
                        'name', flat = True
                    )
    output = '\n'.join(group_names)
    return HttpResponse(output, mimetype = 'text/plain')

@csrf.csrf_protect
def subscribe_for_tags(request):
    """process subscription of users by tags"""
    #todo - use special separator to split tags
    tag_names = request.REQUEST.get('tags','').strip().split()
    pure_tag_names, wildcards = forms.clean_marked_tagnames(tag_names)
    if request.user.is_authenticated():
        if request.method == 'POST':
            if 'ok' in request.POST:
                request.user.mark_tags(
                            pure_tag_names,
                            wildcards,
                            reason = 'good',
                            action = 'add'
                        )
                request.user.message_set.create(
                    message = _('Your tag subscription was saved, thanks!')
                )
            else:
                message = _(
                    'Tag subscription was canceled (<a href="%(url)s">undo</a>).'
                ) % {'url': request.path + '?tags=' + request.REQUEST['tags']}
                request.user.message_set.create(message = message)
            return HttpResponseRedirect(reverse('index'))
        else:
            data = {'tags': tag_names}
            return render_into_skin('subscribe_for_tags.html', data, request)
    else:
        all_tag_names = pure_tag_names + wildcards
        message = _('Please sign in to subscribe for: %(tags)s') \
                    % {'tags': ', '.join(all_tag_names)}
        request.user.message_set.create(message = message)
        request.session['subscribe_for_tags'] = (pure_tag_names, wildcards)
        return HttpResponseRedirect(url_utils.get_login_url())


@decorators.get_only
def api_get_exercises(request):
    """json api for retrieving exercises"""
    query = request.GET.get('query', '').strip()
    if not query:
        return HttpResponseBadRequest('Invalid query')

    if askbot_settings.GROUPS_ENABLED:
        threads = models.Thread.objects.get_visible(user=request.user)
    else:
        threads = models.Thread.objects.all()

    threads = models.Thread.objects.get_for_query(
                                    search_query=query,
                                    qs=threads
                                )

    if should_show_sort_by_relevance():
        threads = threads.extra(order_by = ['-relevance'])
    #todo: filter out deleted threads, for now there is no way
    threads = threads.distinct()[:30]
    thread_list = [{
        'title': escape(thread.title),
        'url': thread.get_absolute_url(),
        'problem_count': thread.get_problem_count(request.user)
    } for thread in threads]
    json_data = simplejson.dumps(thread_list)
    return HttpResponse(json_data, mimetype = "application/json")


@csrf.csrf_exempt
@decorators.post_only
@decorators.ajax_login_required
def set_tag_filter_strategy(request):
    """saves data in the ``User.[email/display]_tag_filter_strategy``
    for the current user
    """
    filter_type = request.POST['filter_type']
    filter_value = int(request.POST['filter_value'])
    assert(filter_type in ('display', 'email'))
    if filter_type == 'display':
        assert(filter_value in dict(const.TAG_DISPLAY_FILTER_STRATEGY_CHOICES))
        request.user.display_tag_filter_strategy = filter_value
    else:
        assert(filter_value in dict(const.TAG_EMAIL_FILTER_STRATEGY_CHOICES))
        request.user.email_tag_filter_strategy = filter_value
    request.user.save()
    return HttpResponse('', mimetype = "application/json")


@login_required
@csrf.csrf_protect
def close(request, id):#close exercise
    """view to initiate and process
    exercise close
    """
    exercise = get_object_or_404(models.Post, post_type='exercise', id=id)
    try:
        if request.method == 'POST':
            form = forms.CloseForm(request.POST)
            if form.is_valid():
                reason = form.cleaned_data['reason']

                request.user.close_exercise(
                                        exercise = exercise,
                                        reason = reason
                                    )
            return HttpResponseRedirect(exercise.get_absolute_url())
        else:
            request.user.assert_can_close_exercise(exercise)
            form = forms.CloseForm()
            data = {
                'exercise': exercise,
                'form': form,
            }
            return render_into_skin('close.html', data, request)
    except exceptions.PermissionDenied, e:
        request.user.message_set.create(message = unicode(e))
        return HttpResponseRedirect(exercise.get_absolute_url())

@login_required
@csrf.csrf_protect
def reopen(request, id):#re-open exercise
    """view to initiate and process
    exercise close

    this is not an ajax view
    """

    exercise = get_object_or_404(models.Post, post_type='exercise', id=id)
    # open exercise
    try:
        if request.method == 'POST' :
            request.user.reopen_exercise(exercise)
            return HttpResponseRedirect(exercise.get_absolute_url())
        else:
            request.user.assert_can_reopen_exercise(exercise)
            closed_by_profile_url = exercise.thread.closed_by.get_profile_url()
            closed_by_username = exercise.thread.closed_by.username
            data = {
                'exercise' : exercise,
                'closed_by_profile_url': closed_by_profile_url,
                'closed_by_username': closed_by_username,
            }
            return render_into_skin('reopen.html', data, request)

    except exceptions.PermissionDenied, e:
        request.user.message_set.create(message = unicode(e))
        return HttpResponseRedirect(exercise.get_absolute_url())


@csrf.csrf_exempt
@decorators.ajax_only
def swap_exercise_with_problem(request):
    """receives two json parameters - problem id
    and new exercise title
    the view is made to be used only by the site administrator
    or moderators
    """
    if request.user.is_authenticated():
        if request.user.is_administrator() or request.user.is_moderator():
            problem = models.Post.objects.get_problems(request.user).get(id = request.POST['problem_id'])
            new_exercise = problem.swap_with_exercise(new_title = request.POST['new_title'])
            return {
                'id': new_exercise.id,
                'slug': new_exercise.slug
            }
    raise Http404

@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
def upvote_comment(request):
    if request.user.is_anonymous():
        raise exceptions.PermissionDenied(_('Please sign in to vote'))
    form = forms.VoteForm(request.POST)
    if form.is_valid():
        comment_id = form.cleaned_data['post_id']
        cancel_vote = form.cleaned_data['cancel_vote']
        comment = get_object_or_404(models.Post, post_type='comment', id=comment_id)
        process_vote(
            post = comment,
            vote_direction = 'up',
            user = request.user
        )
    else:
        raise ValueError
    #FIXME: rename js
    return {'score': comment.points}

@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
def delete_post(request):
    if request.user.is_anonymous():
        raise exceptions.PermissionDenied(_('Please sign in to delete/restore posts'))
    form = forms.VoteForm(request.POST)
    if form.is_valid():
        post_id = form.cleaned_data['post_id']
        post = get_object_or_404(
            models.Post,
            post_type__in = ('exercise', 'problem'),
            id = post_id
        )
        if form.cleaned_data['cancel_vote']:
            request.user.restore_post(post)
        else:
            request.user.delete_post(post)
    else:
        raise ValueError
    return {'is_deleted': post.deleted}

#askbot-user communication system
@csrf.csrf_exempt
def read_message(request):#marks message a read
    if request.method == "POST":
        if request.POST['formdata'] == 'required':
            request.session['message_silent'] = 1
            if request.user.is_authenticated():
                request.user.delete_messages()
    return HttpResponse('')


@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
@decorators.admins_only
def edit_group_membership(request):
    #todo: this call may need to go.
    #it used to be the one creating groups
    #from the user profile page
    #we have a separate method
    form = forms.EditGroupMembershipForm(request.POST)
    if form.is_valid():
        group_name = form.cleaned_data['group_name']
        user_id = form.cleaned_data['user_id']
        try:
            user = models.User.objects.get(id=user_id)
        except models.User.DoesNotExist:
            raise exceptions.PermissionDenied(
                'user with id %d not found' % user_id
            )

        action = form.cleaned_data['action']
        #warning: possible race condition
        if action == 'add':
            group_params = {'name': group_name, 'user': user}
            group = models.Group.objects.get_or_create(**group_params)
            request.user.edit_group_membership(user, group, 'add')
            template = get_template('widgets/group_snippet.html')
            return {
                'name': group.name,
                'description': getattr(group.tag_wiki, 'text', ''),
                'html': template.render({'group': group})
            }
        elif action == 'remove':
            try:
                group = models.Group.objects.get(group_name = group_name)
                request.user.edit_group_membership(user, group, 'remove')
            except models.Group.DoesNotExist:
                raise exceptions.PermissionDenied()
        else:
            raise exceptions.PermissionDenied()
    else:
        raise exceptions.PermissionDenied()


@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
@decorators.admins_only
def save_group_logo_url(request):
    """saves urls for the group logo"""
    form = forms.GroupLogoURLForm(request.POST)
    if form.is_valid():
        group_id = form.cleaned_data['group_id']
        image_url = form.cleaned_data['image_url']
        group = models.Group.objects.get(id = group_id)
        group.logo_url = image_url
        group.save()
    else:
        raise ValueError('invalid data found when saving group logo')

@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
@decorators.admins_only
def add_group(request):
    group_name = request.POST.get('group')
    if group_name:
        group = models.Group.objects.get_or_create(
                            name=group_name,
                            openness=models.Group.OPEN,
                            user=request.user,
                        )

        url = reverse('users_by_group', kwargs={'group_id': group.id,
                   'group_slug': slugify(group_name)})
        response_dict = dict(group_name = group_name,
                             url = url )
        return response_dict

@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
@decorators.admins_only
def delete_group_logo(request):
    group_id = IntegerField().clean(int(request.POST['group_id']))
    group = models.Group.objects.get(id = group_id)
    group.logo_url = None
    group.save()


@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
@decorators.admins_only
def delete_post_reject_reason(request):
    reason_id = IntegerField().clean(int(request.POST['reason_id']))
    reason = models.PostFlagReason.objects.get(id = reason_id)
    reason.delete()


@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
@decorators.admins_only
def toggle_group_profile_property(request):
    #todo: this might be changed to more general "toggle object property"
    group_id = IntegerField().clean(int(request.POST['group_id']))
    property_name = CharField().clean(request.POST['property_name'])
    assert property_name in (
                        'moderate_email',
                        'moderate_problems_to_enquirers',
                        'is_vip'
                    )
    group = models.Group.objects.get(id = group_id)
    new_value = not getattr(group, property_name)
    setattr(group, property_name, new_value)
    group.save()
    return {'is_enabled': new_value}


@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
@decorators.admins_only
def set_group_openness(request):
    group_id = IntegerField().clean(int(request.POST['group_id']))
    value = IntegerField().clean(int(request.POST['value']))
    group = models.Group.objects.get(id=group_id)
    group.openness = value
    group.save()


@csrf.csrf_exempt
@decorators.ajax_only
@decorators.admins_only
def edit_object_property_text(request):
    model_name = CharField().clean(request.REQUEST['model_name'])
    object_id = IntegerField().clean(request.REQUEST['object_id'])
    property_name = CharField().clean(request.REQUEST['property_name'])

    accessible_fields = (
        ('Group', 'preapproved_emails'),
        ('Group', 'preapproved_email_domains')
    )

    if (model_name, property_name) not in accessible_fields:
        raise exceptions.PermissionDenied()

    obj = models.get_model(model_name).objects.get(id=object_id)
    if request.method == 'POST':
        text = CharField().clean(request.POST['text'])
        setattr(obj, property_name, text)
        obj.save()
    elif request.method == 'GET':
        return {'text': getattr(obj, property_name)}
    else:
        raise exceptions.PermissionDenied()


@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
def join_or_leave_group(request):
    """called when user wants to join/leave
    ask to join/cancel join request, depending
    on the groups acceptance level for the given user

    returns resulting "membership_level"
    """
    if request.user.is_anonymous():
        raise exceptions.PermissionDenied()

    Group = models.Group
    Membership = models.GroupMembership

    group_id = IntegerField().clean(request.POST['group_id'])
    group = Group.objects.get(id=group_id)

    membership = request.user.get_group_membership(group)
    if membership is None:
        membership = request.user.join_group(group)
        new_level = membership.get_level_display()
    else:
        membership.delete()
        new_level = Membership.get_level_value_display(Membership.NONE)

    return {'membership_level': new_level}


@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
@decorators.admins_only
def save_post_reject_reason(request):
    """saves post reject reason and returns the reason id
    if reason_id is not given in the input - a new reason is created,
    otherwise a reason with the given id is edited and saved
    """
    form = forms.EditRejectReasonForm(request.POST)
    if form.is_valid():
        title = form.cleaned_data['title']
        details = form.cleaned_data['details']
        if form.cleaned_data['reason_id'] is None:
            reason = request.user.create_post_reject_reason(
                title = title, details = details
            )
        else:
            reason_id = form.cleaned_data['reason_id']
            reason = models.PostFlagReason.objects.get(id = reason_id)
            request.user.edit_post_reject_reason(
                reason, title = title, details = details
            )
        return {
            'reason_id': reason.id,
            'title': title,
            'details': details
        }
    else:
        raise Exception(forms.format_form_errors(form))

@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
@decorators.admins_only
def moderate_suggested_tag(request):
    """accepts or rejects a suggested tag
    if thread id is given, then tag is
    applied to or removed from only one thread,
    otherwise the decision applies to all threads
    """
    form = forms.ModerateTagForm(request.POST)
    if form.is_valid():
        tag_id = form.cleaned_data['tag_id']
        thread_id = form.cleaned_data.get('thread_id', None)

        try:
            tag = models.Tag.objects.get(id=tag_id)#can tag not exist?
        except models.Tag.DoesNotExist:
            return

        if thread_id:
            threads = models.Thread.objects.filter(id = thread_id)
        else:
            threads = tag.threads.all()

        if form.cleaned_data['action'] == 'accept':
            #todo: here we lose ability to come back
            #to the tag moderation and approve tag to
            #other threads later for the case where tag.used_count > 1
            tag.status = models.Tag.STATUS_ACCEPTED
            tag.save()
            for thread in threads:
                thread.add_tag(
                    tag_name = tag.name,
                    user = tag.created_by,
                    timestamp = datetime.datetime.now(),
                    silent = True
                )
        else:
            if tag.threads.count() > len(threads):
                for thread in threads:
                    thread.tags.remove(tag)
                tag.used_count = tag.threads.count()
                tag.save()
            elif tag.status == models.Tag.STATUS_SUGGESTED:
                tag.delete()
    else:
        raise Exception(forms.format_form_errors(form))


@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
def save_draft_exercise(request):
    """saves draft exercises"""
    #todo: allow drafts for anonymous users
    if request.user.is_anonymous():
        return

    form = forms.DraftExerciseForm(request.POST)
    if form.is_valid():
        title = form.cleaned_data.get('title', '')
        text = form.cleaned_data.get('text', '')
        tagnames = form.cleaned_data.get('tagnames', '')
        if title or text or tagnames:
            try:
                draft = models.DraftExercise.objects.get(author=request.user)
            except models.DraftExercise.DoesNotExist:
                draft = models.DraftExercise()

            draft.title = title
            draft.text = text
            draft.tagnames = tagnames
            draft.author = request.user
            draft.save()


@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
def save_draft_problem(request):
    """saves draft problems"""
    #todo: allow drafts for anonymous users
    if request.user.is_anonymous():
        return

    form = forms.DraftProblemForm(request.POST)
    if form.is_valid():
        thread_id = form.cleaned_data['thread_id']
        try:
            thread = models.Thread.objects.get(id=thread_id)
        except models.Thread.DoesNotExist:
            return
        try:
            draft = models.DraftProblem.objects.get(
                                            thread=thread,
                                            author=request.user
                                    )
        except models.DraftProblem.DoesNotExist:
            draft = models.DraftProblem()

        draft.author = request.user
        draft.thread = thread
        draft.text = form.cleaned_data.get('text', '')
        draft.save()

@decorators.get_only
def get_users_info(request):
    """retuns list of user names and email addresses
    of "fake" users - so that admins can post on their
    behalf"""
    if request.user.is_anonymous():
        return HttpResponseForbidden()

    query = request.GET['q']
    limit = IntegerField().clean(request.GET['limit'])

    users = models.User.objects
    user_info_list = users.filter(username__istartswith=query)

    if request.user.is_administrator_or_moderator():
        user_info_list = user_info_list.values_list('username', 'email')
    else:
        user_info_list = user_info_list.values_list('username')

    result_list = ['|'.join(info) for info in user_info_list[:limit]]
    return HttpResponse('\n'.join(result_list), mimetype = 'text/plain')

@csrf.csrf_protect
def share_exercise_with_group(request):
    form = forms.ShareExerciseForm(request.POST)
    try:
        if form.is_valid():

            thread_id = form.cleaned_data['thread_id']
            group_name = form.cleaned_data['recipient_name']

            thread = models.Thread.objects.get(id=thread_id)
            exercise_post = thread._exercise_post()

            #get notif set before
            sets1 = exercise_post.get_notify_sets(
                                    mentioned_users=list(),
                                    exclude_list=[request.user,]
                                )

            #share the post
            if group_name == askbot_settings.GLOBAL_GROUP_NAME:
                thread.make_public(recursive=True)
            else:
                group = models.Group.objects.get(name=group_name)
                thread.add_to_groups((group,), recursive=True)

            #get notif sets after
            sets2 = exercise_post.get_notify_sets(
                                    mentioned_users=list(),
                                    exclude_list=[request.user,]
                                )

            notify_sets = {
                'for_mentions': sets2['for_mentions'] - sets1['for_mentions'],
                'for_email': sets2['for_email'] - sets1['for_email'],
                'for_inbox': sets2['for_inbox'] - sets1['for_inbox']
            }

            exercise_post.issue_update_notifications(
                updated_by=request.user,
                notify_sets=notify_sets,
                activity_type=const.TYPE_ACTIVITY_POST_SHARED,
                timestamp=datetime.datetime.now()
            )

            return HttpResponseRedirect(thread.get_absolute_url())
    except Exception:
        error_message = _('Sorry, looks like sharing request was invalid')
        request.user.message_set.create(message=error_message)
        return HttpResponseRedirect(thread.get_absolute_url())

@csrf.csrf_protect
def share_exercise_with_user(request):
    form = forms.ShareExerciseForm(request.POST)
    try:
        if form.is_valid():

            thread_id = form.cleaned_data['thread_id']
            username = form.cleaned_data['recipient_name']

            thread = models.Thread.objects.get(id=thread_id)
            user = models.User.objects.get(username=username)
            group = user.get_personal_group()
            thread.add_to_groups([group], recursive=True)
            #notify the person
            #todo: see if user could already see the post - b/f the sharing
            notify_sets = {
                'for_inbox': set([user]),
                'for_mentions': set([user]),
                'for_email': set([user])
            }
            thread._exercise_post().issue_update_notifications(
                updated_by=request.user,
                notify_sets=notify_sets,
                activity_type=const.TYPE_ACTIVITY_POST_SHARED,
                timestamp=datetime.datetime.now()
            )

            return HttpResponseRedirect(thread.get_absolute_url())
    except Exception:
        error_message = _('Sorry, looks like sharing request was invalid')
        request.user.message_set.create(message=error_message)
        return HttpResponseRedirect(thread.get_absolute_url())

@csrf.csrf_protect
def moderate_group_join_request(request):
    """moderator of the group can accept or reject a new user"""
    request_id = IntegerField().clean(request.POST['request_id'])
    action = request.POST['action']
    assert(action in ('approve', 'deny'))

    activity = get_object_or_404(models.Activity, pk=request_id)
    group = activity.content_object
    applicant = activity.user

    if group.has_moderator(request.user):
        group_membership = models.GroupMembership.objects.get(
                                            user=applicant, group=group
                                        )
        if action == 'approve':
            group_membership.level = models.GroupMembership.FULL
            group_membership.save()
            msg_data = {'user': applicant.username, 'group': group.name}
            message = _('%(user)s, welcome to group %(group)s!') % msg_data
            applicant.message_set.create(message=message)
        else:
            group_membership.delete()

        activity.delete()
        url = request.user.get_absolute_url() + '?sort=inbox&section=join_requests'
        return HttpResponseRedirect(url)
    else:
        raise Http404

@decorators.get_only
def get_editor(request):
    """returns bits of html for the tinymce editor in a dictionary with keys:
    * html - the editor element
    * scripts - an array of script tags
    * success - True
    """
    config = simplejson.loads(request.GET['config'])
    form = forms.EditorForm(editor_attrs=config)
    editor_html = render_text_into_skin(
        '{{ form.media }} {{ form.editor }}',
        {'form': form},
        request
    )
    #parse out javascript and dom, and return them separately
    #we need that, because js needs to be added in a special way
    html_soup = BeautifulSoup(editor_html)

    parsed_scripts = list()
    for script in html_soup.find_all('script'):
        parsed_scripts.append({
            'contents': script.string,
            'src': script.get('src', None)
        })

    data = {
        'html': str(html_soup.textarea),
        'scripts': parsed_scripts,
        'success': True
    }
    return HttpResponse(simplejson.dumps(data), mimetype='application/json')

@csrf.csrf_exempt
@decorators.ajax_only
@decorators.post_only
def publish_problem(request):
    """will publish or unpublish problem, if
    current thread is moderated
    """
    denied_msg = _('Sorry, only thread moderators can use this function')
    if request.user.is_authenticated():
        if request.user.is_administrator_or_moderator() is False:
            raise exceptions.PermissionDenied(denied_msg)
    #todo: assert permission
    problem_id = IntegerField().clean(request.POST['problem_id'])
    problem = models.Post.objects.get(id=problem_id, post_type='problem')

    if problem.thread.has_moderator(request.user) is False:
        raise exceptions.PermissionDenied(denied_msg)

    enquirer = problem.thread._exercise_post().author
    enquirer_group = enquirer.get_personal_group()

    if problem.has_group(enquirer_group):
        message = _('The problem is now unpublished')
        problem.remove_from_groups([enquirer_group])
    else:
        problem.add_to_groups([enquirer_group])
        message = _('The problem is now published')
        #todo: notify enquirer by email about the post
    request.user.message_set.create(message=message)
    return {'redirect_url': problem.get_absolute_url()}
