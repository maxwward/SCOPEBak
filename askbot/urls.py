"""
askbot askbot url configuraion file
"""
import os.path
from django.conf import settings
from django.conf.urls.defaults import url, patterns, include
from django.conf.urls.defaults import handler500, handler404
from django.contrib import admin
from askbot import views
from askbot.feed import RssLastestExercisesFeed, RssIndividualExerciseFeed
from askbot.sitemap import ExercisesSitemap
from askbot.skins.utils import update_media_revision

admin.autodiscover()
update_media_revision()#needs to be run once, so put it here

if getattr(settings, "ASKBOT_TRANSLATE_URL", False):
    from django.utils.translation import ugettext as _
else:
    _ = lambda s:s

feeds = {
    'rss': RssLastestExercisesFeed,
    'exercise':RssIndividualExerciseFeed
}
sitemaps = {
    'exercises': ExercisesSitemap
}

APP_PATH = os.path.dirname(__file__)
urlpatterns = patterns('',
    url(r'^$', views.readers.index, name='index'),
    url(
        r'^sitemap.xml$',
        'django.contrib.sitemaps.views.sitemap',
        {'sitemaps': sitemaps},
        name='sitemap'
    ),
    #no translation for this url!!
    url(r'import-data/$', views.writers.import_data, name='import_data'),
    url(r'^%s$' % _('about/'), views.meta.about, name='about'),
    url(r'^%s$' % _('faq/'), views.meta.faq, name='faq'),
    url(r'^%s$' % _('privacy/'), views.meta.privacy, name='privacy'),
    url(r'^%s$' % _('help/'), views.meta.help, name='help'),
    url(
        r'^%s(?P<id>\d+)/%s$' % (_('problems/'), _('edit/')),
        views.writers.edit_problem,
        name='edit_problem'
    ),
    url(
        r'^%s(?P<id>\d+)/%s$' % (_('answers/'), _('edit/')),
        views.writers.edit_problem,
        name='edit_answer'
    ),
    url(
        r'^%s(?P<id>\d+)/%s$' % (_('problems/'), _('revisions/')),
        views.readers.revisions,
        kwargs = {'post_type': 'problem'},
        name='problem_revisions'
    ),

    # BEGIN Exercises (main page) urls. All this urls work both normally and through ajax

    url(
        # Note that all parameters, even if optional, are provided to the view. Non-present ones have None value.
        (r'^%s' % _('exercises') +
            r'(%s)?' % r'/scope:(?P<scope>\w+)' +
            r'(%s)?' % r'/sort:(?P<sort>[\w\-]+)' +
            r'(%s)?' % r'/query:(?P<query>[^/]+)' +  # INFO: exercise string cannot contain slash (/), which is a section terminator
            r'(%s)?' % r'/tags:(?P<tags>[\w+.#,-]+)' + # Should match: const.TAG_CHARS + ','; TODO: Is `#` char decoded by the time URLs are processed ??
            r'(%s)?' % r'/author:(?P<author>\d+)' +
            r'(%s)?' % r'/page:(?P<page>\d+)' +
        r'/$'),

        views.readers.exercises,
        name='exercises'
    ),
    # END main page urls

    url(
        r'^api/get_exercises/',
        views.commands.api_get_exercises,
        name='api_get_exercises'
    ),
    url(
        r'^get-thread-shared-users/',
        views.commands.get_thread_shared_users,
        name='get_thread_shared_users'
    ),
    url(
        r'^get-thread-shared-groups/',
        views.commands.get_thread_shared_groups,
        name='get_thread_shared_groups'
    ),
    url(
        r'^moderate-group-join-request/',
        views.commands.moderate_group_join_request,
        name='moderate_group_join_request'
    ),
    url(
        r'^save-draft-exercise/',
        views.commands.save_draft_exercise,
        name = 'save_draft_exercise'
    ),
    url(
        r'^save-draft-problem/',
        views.commands.save_draft_problem,
        name = 'save_draft_problem'
    ),
    url(
        r'^share-exercise-with-group/',
        views.commands.share_exercise_with_group,
        name='share_exercise_with_group'
    ),
    url(
        r'^share-exercise-with-user/',
        views.commands.share_exercise_with_user,
        name='share_exercise_with_user'
    ),
    url(
        r'^get-users-info/',
        views.commands.get_users_info,
        name='get_users_info'
    ),
    url(
        r'^get-editor/',
        views.commands.get_editor,
        name='get_editor'
    ),
    url(
        r'^%s%s$' % (_('exercises/'), _('ask/')),
        views.writers.ask,
        name='ask'
    ),
    url(
        r'^%s(?P<id>\d+)/%s$' % (_('exercises/'), _('edit/')),
        views.writers.edit_exercise,
        name='edit_exercise'
    ),
    url(#this url is both regular and ajax
        r'^%s(?P<id>\d+)/%s$' % (_('exercises/'), _('retag/')),
        views.writers.retag_exercise,
        name='retag_exercise'
    ),
    url(
        r'^%s(?P<id>\d+)/%s$' % (_('exercises/'), _('close/')),
        views.commands.close,
        name='close'
    ),
    url(
        r'^%s(?P<id>\d+)/%s$' % (_('exercises/'), _('reopen/')),
        views.commands.reopen,
        name='reopen'
    ),
    url(
        r'^%s(?P<id>\d+)/%s$' % (_('exercises/'), _('problem/')),
        views.writers.problem,
        name='problem'
    ),
    #Hans: process the answer form
    url(
        r'^%s(?P<mid>\d+)/(?P<pid>\d+)/%s$' % (_('exercises/'), _('answer/')),
        views.writers.post_new_answer,
        name='post_new_answer'
    ),
    #Hans: hack the dispatcher to redirect to the answer form
    url(
        r'^%s(?P<mid>\d+)/(?P<pid>\d+)/%s$' % (_('exercise/'), _('post-answer/')),
        views.readers.new_answer_form,
        name='new_answer_form'
    ),
    url(#ajax only
        r'^%s(?P<id>\d+)/%s$' % (_('exercises/'), _('vote/')),
        views.commands.vote,
        name='vote'
    ),
    url(
        r'^%s(?P<id>\d+)/%s$' % (_('exercises/'), _('revisions/')),
        views.readers.revisions,
        kwargs = {'post_type': 'exercise'},
        name='exercise_revisions'
    ),
    url(#ajax only
        r'^comment/upvote/$',
        views.commands.upvote_comment,
        name = 'upvote_comment'
    ),
    url(#ajax only
        r'^post/delete/$',
        views.commands.delete_post,
        name = 'delete_post'
    ),
    url(#ajax only
        r'^post_comments/$',
        views.writers.post_comments,
        name='post_comments'
    ),
    url(#ajax only
        r'^edit_comment/$',
        views.writers.edit_comment,
        name='edit_comment'
    ),
    url(#ajax only
        r'^comment/delete/$',
        views.writers.delete_comment,
        name='delete_comment'
    ),
    url(#ajax only
        r'^comment/get_text/$',
        views.readers.get_comment,
        name='get_comment'
    ),
    url(#post only
        r'^comment/convert/$',
        views.writers.comment_to_problem,
        name='comment_to_problem'
    ),
    url(#post only
        r'^problem/convert/$',
        views.writers.problem_to_comment,
        name='problem_to_comment'
    ),
    url(#post only
        r'^answer/convert/$',
        views.writers.problem_to_comment,
        name='answer_to_comment'
    ),
    url(#post only
        r'^problem/publish/$',
        views.commands.publish_problem,
        name='publish_problem'
    ),
    url(
        r'^%s$' % _('tags/'),
        views.readers.tags,
        name='tags'
    ),
    url(
        r'^%s$' % _('suggested-tags/'),
        views.meta.list_suggested_tags,
        name = 'list_suggested_tags'
    ),
    url(#ajax only
        r'^%s$' % 'moderate-suggested-tag',
        views.commands.moderate_suggested_tag,
        name = 'moderate_suggested_tag'
    ),
    #todo: collapse these three urls and use an extra json data var
    url(#ajax only
        r'^%s%s$' % ('mark-tag/', 'interesting/'),
        views.commands.mark_tag,
        kwargs={'reason':'good','action':'add'},
        name='mark_interesting_tag'
    ),
    url(#ajax only
        r'^%s%s$' % ('mark-tag/', 'ignored/'),
        views.commands.mark_tag,
        kwargs={'reason':'bad','action':'add'},
        name='mark_ignored_tag'
    ),
    url(#ajax only
        r'^%s%s$' % ('mark-tag/', 'subscribed/'),
        views.commands.mark_tag,
        kwargs={'reason':'subscribed','action':'add'},
        name='mark_subscribed_tag'
    ),
    url(#ajax only
        r'^unmark-tag/',
        views.commands.mark_tag,
        kwargs={'action':'remove'},
        name='unmark_tag'
    ),
    url(#ajax only
        r'^set-tag-filter-strategy/',
        views.commands.set_tag_filter_strategy,
        name = 'set_tag_filter_strategy'
    ),
    url(
        r'^get-tags-by-wildcard/',
        views.commands.get_tags_by_wildcard,
        name = 'get_tags_by_wildcard'
    ),
    url(
        r'^get-tag-list/',
        views.commands.get_tag_list,
        name = 'get_tag_list'
    ),
    url(
        r'^load-object-description/',
        views.commands.load_object_description,
        name = 'load_object_description'
    ),
    url(#ajax only
        r'^save-object-description/',
        views.commands.save_object_description,
        name = 'save_object_description'
    ),
    url(#ajax only
        r'^add-tag-category/',
        views.commands.add_tag_category,
        name = 'add_tag_category'
    ),
    url(#ajax only
        r'^rename-tag/',
        views.commands.rename_tag,
        name = 'rename_tag'
    ),
    url(#
        r'^delete-tag/',
        views.commands.delete_tag,
        name = 'delete_tag'
    ),
    url(#ajax only
        r'^save-group-logo-url/',
        views.commands.save_group_logo_url,
        name = 'save_group_logo_url'
    ),
    url(#ajax only
        r'^delete-group-logo/',
        views.commands.delete_group_logo,
        name = 'delete_group_logo'
    ),
    url(#ajax only
        r'^add-group/',
        views.commands.add_group,
        name = 'add_group'
    ),
    url(#ajax only
        r'^toggle-group-profile-property/',
        views.commands.toggle_group_profile_property,
        name='toggle_group_profile_property'
    ),
    url(#ajax only
        r'^set-group-openness/',
        views.commands.set_group_openness,
        name='set_group_openness'
    ),
    url(#ajax only
        r'^edit-object-property-text/',
        views.commands.edit_object_property_text,
        name = 'edit_object_property_text'
    ),
    url(
        r'^get-groups-list/',
        views.commands.get_groups_list,
        name = 'get_groups_list'
    ),
    url(
        r'^swap-exercise-with-problem/',
        views.commands.swap_exercise_with_problem,
        name = 'swap_exercise_with_problem'
    ),
    url(
        r'^%s$' % _('subscribe-for-tags/'),
        views.commands.subscribe_for_tags,
        name = 'subscribe_for_tags'
    ),
    url(
        r'^%s$' % _('users/'),
        views.users.show_users,
        name='users'
    ),
    url(
        r'^%s%s(?P<group_id>\d+)/(?P<group_slug>.*)/$' % (_('users/'), _('by-group/')),
        views.users.show_users,
        kwargs = {'by_group': True},
        name = 'users_by_group'
    ),
    #todo: rename as user_edit, b/c that's how template is named
    url(
        r'^%s(?P<id>\d+)/%s$' % (_('users/'), _('edit/')),
        views.users.edit_user,
        name ='edit_user'
    ),
    url(
        r'^%s(?P<id>\d+)/(?P<slug>.+)/%s$' % (
            _('users/'),
            _('subscriptions/'),
        ),
        views.users.user,
        kwargs = {'tab_name': 'email_subscriptions'},
        name = 'user_subscriptions'
    ),
    url(
        r'^%s(?P<id>\d+)/(?P<slug>.+)/$' % _('users/'),
        views.users.user,
        name='user_profile'
    ),
    url(
        r'^%s$' % _('groups/'),
        views.users.groups,
        name='groups'
    ),
    url(
        r'^%s$' % _('users/update_has_custom_avatar/'),
        views.users.update_has_custom_avatar,
        name='user_update_has_custom_avatar'
    ),
    url(
        r'^%s$' % _('badges/'),
        views.meta.badges,
        name='badges'
    ),
    url(
        r'^%s(?P<id>\d+)//*' % _('badges/'),
        views.meta.badge,
        name='badge'
    ),
    url(
        r'get-html-template/',
        views.commands.get_html_template,
        name='get_html_template'
    ),
    url(#ajax only
        r'^%s%s$' % (_('messages/'), _('markread/')),
        views.commands.read_message,
        name='read_message'
    ),
    url(#ajax only
        r'^manage-inbox/$',
        views.commands.manage_inbox,
        name='manage_inbox'
    ),
    url(#ajax only
        r'^save-post-reject-reason/$',
        views.commands.save_post_reject_reason,
        name='save_post_reject_reason'
    ),
    url(#ajax only
        r'^delete-post-reject-reason/$',
        views.commands.delete_post_reject_reason,
        name='delete_post_reject_reason'
    ),
    url(#ajax only
        r'^edit-group-membership/$',
        views.commands.edit_group_membership,
        name='edit_group_membership'
    ),
    url(#ajax only
        r'^join-or-leave-group/$',
        views.commands.join_or_leave_group,
        name = 'join_or_leave_group'
    ),
    #widgets url!
    url(
        r'^%s$' % (_('widgets/')),
        views.widgets.widgets,
        name = 'widgets'
    ),

    url(
        r'^%s%s(?P<widget_id>\d+)/$' % (_('widgets/'), _('ask/')),
        views.widgets.ask_widget,
        name = 'ask_by_widget'
    ),
    url(
        r'^%s%s(?P<widget_id>\d+).js$' % (_('widgets/'), _('ask/')),
        views.widgets.render_ask_widget_js,
        name = 'render_ask_widget'
    ),
    url(
        r'^%s%s(?P<widget_id>\d+).css$' % (_('widgets/'), _('ask/')),
        views.widgets.render_ask_widget_css,
        name = 'render_ask_widget_css'
    ),

    url(
        r'^%s%s%s$' % (_('widgets/'), _('ask/'), _('complete/')),
        views.widgets.ask_widget_complete,
        name = 'ask_by_widget_complete'
    ),
    url(
        r'^%s(?P<model>\w+)/%s$' % (_('widgets/'), _('create/')),
        views.widgets.create_widget,
        name = 'create_widget'
    ),
    url(
        r'^%s(?P<model>\w+)/%s(?P<widget_id>\d+)/$' % (_('widgets/'), _('edit/')),
        views.widgets.edit_widget,
        name = 'edit_widget'
    ),
    url(
        r'^%s(?P<model>\w+)/%s(?P<widget_id>\d+)/$' % (_('widgets/'), _('delete/')),
        views.widgets.delete_widget,
        name = 'delete_widget'
    ),

    url(
        r'^%s(?P<model>\w+)/$' % (_('widgets/')),
        views.widgets.list_widgets,
        name = 'list_widgets'
    ),
    url(
        r'^widgets/exercises/(?P<widget_id>\d+)/$',
        views.widgets.exercise_widget,
        name = 'exercise_widget'
    ),
    url(
        r'^feeds/(?P<url>.*)/$',
        'django.contrib.syndication.views.feed',
        {'feed_dict': feeds},
        name='feeds'
    ),
    #upload url is ajax only
    url( r'^%s$' % _('upload/'), views.writers.upload, name='upload'),
    url(r'^%s$' % _('feedback/'), views.meta.feedback, name='feedback'),
    #url(r'^feeds/rss/$', RssLastestExercisesFeed, name="latest_exercises_feed"),
    url(
        r'^doc/(?P<path>.*)$',
        'django.views.static.serve',
        {'document_root': os.path.join(APP_PATH,'doc','build','html').replace('\\','/')},
        name='askbot_docs',
    ),
    url(
        '^custom\.css$',
        views.meta.config_variable,
        kwargs = {
            'variable_name': 'CUSTOM_CSS',
            'mimetype': 'text/css'
        },
        name = 'custom_css'
    ),
    url(
        '^custom\.js$',
        views.meta.config_variable,
        kwargs = {
            'variable_name': 'CUSTOM_JS',
            'mimetype': 'text/javascript'
        },
        name = 'custom_js'
    ),
    url(
        r'^jsi18n/$',
        'django.views.i18n.javascript_catalog',
        {'domain': 'djangojs','packages': ('askbot',)},
        name = 'askbot_jsi18n'
    ),
    url('^messages/', include('group_messaging.urls')),
)

#todo - this url below won't work, because it is defined above
#therefore the stackexchange urls feature won't work
if getattr(settings, 'ASKBOT_USE_STACKEXCHANGE_URLS', False):
    urlpatterns += (url(
        r'^%s(?P<id>\d+)/' % _('exercises/'),
        views.readers.exercise,
        name='exercise'
    ),)
else:
    urlpatterns += (url(
        r'^%s(?P<id>\d+)/' % _('exercise/'),
        views.readers.exercise,
        name='exercise'
    ),)

if 'askbot.deps.django_authopenid' in settings.INSTALLED_APPS:
    urlpatterns += (
        url(r'^%s' % _('account/'), include('askbot.deps.django_authopenid.urls')),
    )

if 'avatar' in settings.INSTALLED_APPS:
    #unforturately we have to wire avatar urls here,
    #because views add and change are adapted to
    #use jinja2 templates
    urlpatterns += (
        url('^avatar/add/$', views.avatar_views.add, name='avatar_add'),
        url(
            '^avatar/change/$',
            views.avatar_views.change,
            name='avatar_change'
        ),
        url(
            '^avatar/delete/$',
            views.avatar_views.delete,
            name='avatar_delete'
        ),
        url(#this urs we inherit from the original avatar app
            '^avatar/render_primary/(?P<user_id>[\+\d]+)/(?P<size>[\d]+)/$',
            views.avatar_views.render_primary,
            name='avatar_render_primary'
        ),
    )
